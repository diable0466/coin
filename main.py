import os, discord, ccxt, requests, math
import pandas as pd
import ta
from discord.ext import commands, tasks
from discord import app_commands
from dotenv import load_dotenv
from flask import Flask
from threading import Thread

# 환경 변수 로드
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")

# 바이낸스 연결
exchange = ccxt.binance({
    'apiKey': BINANCE_API_KEY,
    'secret': BINANCE_SECRET_KEY,
    'enableRateLimit': True
})

# Flask 웹 서버 (UptimeRobot용)
app = Flask('')
@app.route('/')
def home():
    return "봇이 작동 중이에요!"
Thread(target=lambda: app.run(host='0.0.0.0', port=8080)).start()

# 디스코드 봇 설정
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='/', intents=intents)
positions = {}

### 🔍 기술 분석 함수 ###
def analyze_coin(coin="BTC"):
    symbol = f"{coin.upper()}/USDT"
    df = pd.DataFrame(exchange.fetch_ohlcv(symbol, '1h', limit=100),
                      columns=["time", "open", "high", "low", "close", "volume"])
    df["close"] = df["close"].astype(float).dropna()
    if df.empty or len(df) < 50:
        return ["❌ 데이터 부족"], 0

    price = df['close'].iloc[-1]
    try:
        rsi = ta.momentum.RSIIndicator(df['close']).rsi().iloc[-1]
        macd_val = ta.trend.MACD(df['close']).macd_diff().iloc[-1]
        stoch = ta.momentum.StochRSIIndicator(df['close']).stochrsi_k().iloc[-1]
        ema20 = ta.trend.EMAIndicator(df['close'], 20).ema_indicator().iloc[-1]
        ema50 = ta.trend.EMAIndicator(df['close'], 50).ema_indicator().iloc[-1]
        ema100 = ta.trend.EMAIndicator(df['close'], 100).ema_indicator().iloc[-1]
        ema200 = ta.trend.EMAIndicator(df['close'], 200).ema_indicator().iloc[-1]
        boll = ta.volatility.BollingerBands(df['close'])
        upper = boll.bollinger_hband().iloc[-1]
        lower = boll.bollinger_lband().iloc[-1]
        center = boll.bollinger_mavg().iloc[-1]
    except Exception as e:
        return [f"❌ 분석 오류: {e}"], 0

    # RSI 환산
    rsi_score = round(((rsi - 35) / 35) * 50 + 50)
    if rsi >= 71:
        rsi_score = round(100 + ((rsi - 71) / 29) * 100)
    elif rsi < 0:
        rsi_score = round((rsi - 35) / 35 * 50)

    # MACD 환산: 시세 기준
    macd_score = round((macd_val / price) * 10000)

    # EMA 구조 평가
    if ema20 > ema50 > ema100 > ema200:
        ema_score = 100
    elif ema200 > ema100 > ema50 > ema20:
        ema_score = -100
    else:
        ema_score = ((ema20 - ema50) + (ema50 - ema100) + (ema100 - ema200)) / price * 100

    # StochRSI 환산
    stoch_score = round((stoch - 0.5) * 200 + 50)

    # 볼린저밴드
    if price > upper:
        boll_score = round(100 + ((price - upper) / center) * 100)
    elif price < lower:
        boll_score = round(-((lower - price) / center) * 100)
    else:
        boll_score = round(((price - center) / (upper - lower)) * 100)
    else:
        boll_score = 0 # 또는 예외처리

    # 평균 계산
    logs = [
        f"RSI: {round(rsi, 2)} → {rsi_score}%",
        f"MACD: {round(macd_val, 6)} → {macd_score}%",
        f"EMA 정렬: {round(ema_score)}%",
        f"StochRSI: {round(stoch, 2)} → {stoch_score}%",
        f"Bollinger Band: → {boll_score}%"
    ]
    avg = round(sum([rsi_score, macd_score, ema_score, stoch_score, boll_score]) / 5)
    return logs, avg

### 🧠 분석 명령어 ###
@bot.tree.command(name="분석", description="코인을 분석하고 롱/숏 확률을 알려줘요.")
@app_commands.describe(coin="예: BTC, ETH")
async def 분석(interaction: discord.Interaction, coin: str = "BTC"):
    await interaction.response.defer()
    try:
        logs, score = analyze_coin(coin)
        msg = f"📊 {coin.upper()} 분석 결과\n\n"
        msg += "\n".join(logs)
        msg += f"\n\n🎯 롱 확률: {score}%\n📉 숏 확률: {100 - score}%"
        await interaction.followup.send(msg)
    except Exception as e:
        await interaction.followup.send(f"❌ 오류 발생: {e}")

@bot.tree.command(name="매수", description="지정한 코인을 실시간 가격 기준으로 매수합니다.")
@app_commands.describe(coin="예: BTC, ETH", 비율="잔고의 비율 (10/25/50)", 레버리지="없음 또는 최대 5배")
async def 매수(interaction: discord.Interaction, coin: str, 비율: int = 10, 레버리지: int = 1):
    await interaction.response.defer()
    try:
        symbol = f"{coin.upper()}/USDT"
        balance = exchange.fetch_balance()
        usdt = balance['total']['USDT']
        invest = usdt * (비율 / 100)
        if 레버리지 > 1:
            invest *= 레버리지
        price = exchange.fetch_ticker(symbol)["last"]
        amount = round(invest / price, 6)
        exchange.create_market_buy_order(symbol, amount)
        await interaction.followup.send(f"✅ {coin.upper()} {amount}개 매수 완료! (비율 {비율}%, 레버리지 {레버리지}배)")
    except Exception as e:
        await interaction.followup.send(f"❌ 매수 실패: {e}")

@bot.tree.command(name="매도", description="보유 코인의 일부를 시장가로 매도합니다.")
@app_commands.describe(coin="예: BTC, ETH", 비율="매도 비율 (25/50/75/100)")
async def 매도(interaction: discord.Interaction, coin: str, 비율: int = 100):
    await interaction.response.defer()
    try:
        symbol = f"{coin.upper()}/USDT"
        balance = exchange.fetch_balance()
        amount = balance['free'][coin.upper()] * (비율 / 100)
        exchange.create_market_sell_order(symbol, round(amount, 6))
        await interaction.followup.send(f"✅ {coin.upper()} {비율}% 매도 완료!")
    except Exception as e:
        await interaction.followup.send(f"❌ 매도 실패: {e}")

@bot.tree.command(name="자동매수", description="조건을 만족하면 자동으로 매수하고 조건에 따라 청산합니다.")
@app_commands.describe(coin="예: BTC, ETH", 비율="잔고 비율", 조건="롱확률 최소조건", 반복="매수 반복 횟수")
async def 자동매수(interaction: discord.Interaction, coin: str, 비율: int = 10, 조건: int = 70, 반복: int = 1):
    await interaction.response.defer()
    msg = ""
    try:
        for i in range(반복):
            logs, score = analysis(coin)  # 반드시 smart_analysis가 먼저 정의되어 있어야 합니다
            if score >= 조건:
                symbol = f"{coin.upper()}/USDT"
                balance = exchange.fetch_balance()
                usdt = balance['total']['USDT']
                invest = usdt * (비율 / 100)
                price = exchange.fetch_ticker(symbol)["last"]
                amount = round(invest / price, 6)
                exchange.create_market_buy_order(symbol, amount)
                msg += f"🟢 {coin.upper()} 자동매수 {i+1}회차 완료! 롱확률 {score}%\n"

                # 자동청산 로직
                while True:
                    now_price = exchange.fetch_ticker(symbol)["last"]
                    change = (now_price - price) / price * 100
                    _, new_score = smart_analysis(coin)
                    if change >= 2:
                        exchange.create_market_sell_order(symbol, amount)
                        msg += f"🎯 수익률 2% 도달. 익절 완료.\n"
                        break
                    elif new_score < 70:
                        exchange.create_market_sell_order(symbol, amount)
                        msg += f"📉 롱확률 {new_score}% 하락. 손절 처리.\n"
                        break
            else:
                msg += f"❌ 롱확률 {score}% < 조건 {조건}% → 매수 스킵\n"
        await interaction.followup.send(msg)
    except Exception as e:
        await interaction.followup.send(f"❌ 자동매수 실패: {e}")


### ✅ 봇 시작 ###
@bot.event
async def on_ready():
    print(f"{bot.user} 시작됨!")
    try:
        await bot.tree.sync()
        print("✅ 슬래시 명령어 동기화 완료")
    except Exception as e:
        print("❌ 동기화 오류:", e)

bot.run(DISCORD_TOKEN)
