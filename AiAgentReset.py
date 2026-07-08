import os
import time
import requests
import xml.etree.ElementTree as ET
import re
import threading
from datetime import datetime
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton  
from google import genai  
from difflib import SequenceMatcher
from flask import Flask
import yfinance as yf 
from pymongo import MongoClient  # 🥭 మొంగోడిబి లైబ్రరీ సర్

# --- 🌐 Render Web Service కోసం చిన్న ఫ్లాస్క్ సెటప్ ---
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 AI Master MongoDB Smart Bot with Detailed Logs is running 24/7 on Render!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)  

# =====================================================================
# 🌟 Render Environment Variables నుండి కీలను లోడ్ చేసే సెటప్
# =====================================================================
MY_GEMINI_API_KEY_1 = os.environ.get("MY_GEMINI_API_KEY_1", "")
MY_GEMINI_API_KEY_2 = os.environ.get("MY_GEMINI_API_KEY_2", "")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
YOUR_TELEGRAM_CHAT_ID = os.environ.get("YOUR_TELEGRAM_CHAT_ID", "")

# 🥭 మొంగోడిబి కనెక్షన్ స్ట్రింగ్ సెటప్ సర్
MONGO_URI = os.environ.get("MONGO_URI", "")

# --- 🧠 గూగుల్ అఫీషియల్ జెమిని క్లయింట్ సెటప్ ---
client_key1 = genai.Client(api_key=MY_GEMINI_API_KEY_1)
client_key2 = genai.Client(api_key=MY_GEMINI_API_KEY_2)

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# =====================================================================
# 🥭 MongoDB డేటాబేస్ సెటప్ & ఫంక్షన్స్
# =====================================================================
print("🥭 MongoDB కి కనెక్ట్ అవుతున్నాము సర్...")
try:
    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client["TradingBotDB"]  # డేటాబేస్ పేరు
    news_collection = db["processed_news"]  # కలెక్షన్ పేరు
    # పాత వార్తలను వెతికేటప్పుడు స్పీడ్ పెరగడానికి ఇండెక్స్ క్రియేట్ చేస్తున్నాం సర్
    news_collection.create_index("clean_content", unique=False)
    print("✅ MongoDB తో కనెక్షన్ సక్సెస్ అయింది సర్!")
except Exception as mongo_init_err:
    print(f"❌ MongoDB స్టార్టింగ్ లోనే ఫెయిల్ అయింది: {mongo_init_err}")
    db = None
    news_collection = None

# కేవలం టెలిగ్రామ్ ఇన్‌లైన్ బటన్స్ కోసం మాత్రమే ఈ లోకల్ ర్యామ్
analysis_vault = {}


# 📢 కోడ్‌లో వచ్చే ఎర్రర్లను టెలిగ్రామ్‌కు పంపే ప్రత్యేక ఫంక్షన్
def report_error_to_telegram(error_location, error_msg):
    try:
        err_text = f"⚠️ <b>[BOT ERROR ALERT]</b>\n\n" \
                   f"📍 <b>Location:</b> {error_location}\n" \
                   f"❌ <b>Error:</b> <code>{error_msg}</code>\n" \
                   f"⏰ <b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        bot.send_message(YOUR_TELEGRAM_CHAT_ID, err_text, parse_mode="HTML")
    except Exception as telegram_err:
        print(f"❌ ఎర్రర్ రిపోర్ట్ టెలిగ్రామ్‌కు పంపడంలో లోపం: {telegram_err}")

def get_text_match_percentage(text1, text2):
    return SequenceMatcher(None, text1, text2).ratio() * 100

def clean_main_content(text):
    text = text.lower()
    text = re.sub(r'https?://\S+|www\.\S+', '', text)
    text = re.sub(r'[^a-zA-Z0-9\s]', '', text)
    return " ".join(text.split())

# 🌟 టెలిగ్రామ్ ఎర్రర్ రాకుండా టెక్స్ట్ క్లీన్ చేసే సేఫ్ HTML ఫంక్షన్
def clean_for_html(text):
    if not text:
        return ""
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
    text = re.sub(r'`(.*?)`', r'<code>\1</code>', text)
    return text

# విశ్లేషణలు ముక్కలు చేసే సేఫ్ ఫంక్షన్
def send_split_message(chat_id, text_to_send):
    try:
        if len(text_to_send) <= 3000:
            safe_text = clean_for_html(text_to_send)
            bot.send_message(chat_id, safe_text, parse_mode="HTML")
        else:
            for i in range(0, len(text_to_send), 3000):
                chunk = text_to_send[i:i+3000]
                safe_chunk = clean_for_html(chunk)
                bot.send_message(chat_id, safe_chunk, parse_mode="HTML")
                time.sleep(1)
    except Exception as telegram_err:
        print(f"⚠️ టెలిగ్రామ్ మెసేజ్ పంపడంలో లోపం: {telegram_err}")
        report_error_to_telegram("send_split_message", str(telegram_err))
        
# =====================================================================
# 📊 లైవ్ మార్కెట్ నెంబర్స్ తెచ్చే ఫంక్షన్
# =====================================================================
def get_live_market_data():
    print("[LIVE DATA LOG] 📊 అన్ని మార్కెట్ నెంబర్స్ తెస్తున్నాం...")
    tickers = {
        "NIFTY 50": "^NSEI",
        "SENSEX": "^BSESN", 
        "BANK NIFTY": "^NSEBANK",
        "NIFTY IT": "^CNXIT",
        "NIFTY FMCG": "^CNXFMCG",
        "NIFTY METAL": "^CNXMETAL",
        "US 10Y YIELD": "^TNX",
        "DXY": "DX-Y.NYB",
        "BRENT CRUDE": "BZ=F",
        "NASDAQ": "^IXIC",
        "USDINR": "INR=X",
        "YES BANK": "YESBANK.NS",
        "VEDANTA": "VEDL.NS",
        "BALRAMPUR CHINI": "BALRAMCHIN.NS"
    }
    
    live_data = "LIVE MARKET SNAPSHOT:\n"
    for name, symbol in tickers.items():
        try:
            data = yf.Ticker(symbol).history(period="1d")
            if not data.empty:
                close = round(data['Close'].iloc[-1], 2)
                open_price = round(data['Open'].iloc[-1], 2)
                
                if open_price > 0:
                    change_pct = round(((close - open_price) / open_price) * 100, 2)
                else:
                    change_pct = 0.0
                    
                live_data += f"- {name}: {close} ({change_pct}%) | Open: {open_price}\n"
            else:
                live_data += f"- {name}: 0.0\n"
            time.sleep(0.1)
        except Exception as e:
            live_data += f"- {name}: 0.0\n"
            
    print("[LIVE DATA LOG] ✅ అన్ని నెంబర్స్ వచ్చాయి సర్.")
    return live_data

def get_fii_dii_data():
    try:
        url = "https://www.nseindia.com/api/fiidiiTradeReact"
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        session = requests.Session()
        session.get("https://www.nseindia.com", headers=headers, timeout=5)
        res = session.get(url, headers=headers, timeout=5)
        data = res.json()
        
        def clean_value(val):
            if isinstance(val, str):
                return float(val.replace(',', '').strip())
            return float(val)

        fii_buy = clean_value(data[0]['buyValue'])
        fii_sell = clean_value(data[0]['sellValue'])
        dii_buy = clean_value(data[1]['buyValue'])
        dii_sell = clean_value(data[1]['sellValue'])

        fii = round(fii_buy - fii_sell, 2)
        dii = round(dii_buy - dii_sell, 2)
        
        return f"FII/DII PROVISIONAL: FII: {fii} Cr, DII: {dii} Cr"
    except Exception as e:
        print(f"[FII/DII ERROR] {e}")
        return "FII/DII: Data not available"

# =====================================================================
# 📰 Continuous Macro & Sector Surveillance Team (MongoDB Base)
# =====================================================================
def live_research_surveillance_worker():
    global analysis_vault
    print("\n🕵️‍♂️ [START] Live Research Team నిరంతర నిఘా లూప్ ప్రారంభమైంది సర్...")
    
    # 🚀 ఎకనామిక్ టైమ్స్ తో పాటు మనీకంట్రోల్ మ్యూచువల్ ఫండ్స్ ని గూగుల్ రూట్ ద్వారా కనెక్ట్ చేసాం సర్
    macro_feeds = [
        ("ET_Markets_Global", "https://economictimes.indiatimes.com/markets/rssfeeds/2146842.cms"),
        # 🥭 మనీకంట్రోల్ లోని మ్యూచువల్ ఫండ్స్, ఎకానమీ నివేదికలను సురక్షితంగా లాగే గూగుల్ న్యూస్ ఫీడ్ సర్
        ("Moneycontrol_MutualFunds_Via_Google", "https://news.google.com/rss/search?q=site:moneycontrol.com+%22mutual+funds%22+OR+economy&hl=en-IN&gl=IN&ceid=IN:en")
    ]
    
    while True:
        try:
            collected_news = []
            
            # 🛠️ వెబ్‌సైట్లు మనల్ని బ్లాక్ చేయకుండా ఉండటానికి పవర్‌ఫుల్ బ్రౌజర్ హెడర్స్ సర్
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Connection": "keep-alive"
            }
            
            print(f"\n🔄 [{datetime.now().strftime('%H:%M:%S')}] RSS ఫీడ్స్ నుండి వార్తలను సేకరిస్తున్నాను...")
            for source_name, url in macro_feeds:
                try:
                    response = requests.get(url, headers=headers, timeout=6)
                    if response.status_code == 200:
                        root = ET.fromstring(response.content)
                        items = root.findall('.//item')
                        feed_count = 0
                        for item in items[:8]:
                            title = item.find('title').text or ""
                            desc = item.find('description').text or ""
                            clean_desc = re.sub('<[^<]+?>', '', desc)
                            full_text = f"{title} {clean_desc}".strip()
                            if full_text: 
                                collected_news.append((source_name, title, full_text))
                                feed_count += 1
                        print(f"📥 {source_name} నుండి {feed_count} వార్తలు సేకరించాను.")
                except Exception as feed_err: 
                    print(f"❌ {source_name} ఫీడ్ కనెక్ట్ చేయడంలో లోపం: {feed_err}")
                    report_error_to_telegram(f"RSS Fetch ({source_name})", str(feed_err))
                    continue

            print(f"📊 మొత్తం సేకరించిన రా (Raw) వార్తల సంఖ్య: {len(collected_news)}")

            if not collected_news:
                print("💤 వార్తలు ఏవీ దొరకలేదు సర్. 5 నిమిషాల గ్యాప్ తీసుకుంటున్నాను...")
                time.sleep(300)
                continue

            for source, raw_title, news_text in collected_news:
                print(f"\n📰 [ప్రాసెస్ అవుతోంది] శీర్షిక: {raw_title[:60]}... ({source})")
                current_clean_content = clean_main_content(news_text)
                
                # 🥭 [MongoDB Check] ఈ వార్త డేటాబేస్ లో ముందే ఉందో లేదో వెతుకుతుంది సర్
                is_duplicate = False
                if news_collection is not None:
                    try:
                        # ఎగ్జాక్ట్ మ్యాచ్ కోసం వెతుకుతుంది
                        existing = news_collection.find_one({"clean_content": current_clean_content})
                        if existing:
                            is_duplicate = True
                    except Exception as db_err:
                        print(f"⚠️ MongoDB వెతకడంలో లోపం: {db_err}")
                
                if is_duplicate: 
                    print(f"⏩ [SKIP] ఈ వార్త ఇప్పటికే MongoDB లో ఉంది (Duplicate). వదిలేస్తున్నాను సర్.")
                    continue
                
                print(f"⏳ రేట్ లిమిట్ రాకుండా ఉండటానికి 30 సెకన్లు ఆగుతున్నాను సర్...")
                time.sleep(30)
                
                print(f"✅ [NEW NEWS] జెమిని AI విశ్లేషణకు పంపుతున్నాను...")
                
                # 💥 మీ పాత అద్భుతమైన ప్రాంప్ట్‌కు 'గూగుల్ లైవ్ సెర్చ్' కండిషన్స్ యాడ్ చేసాం సర్
                prompt = f"""nuvvu oka Senior Global Research Analyst vi. 
ఈ పరిణామాన్ని విశ్లేషించు: {news_text}

CRITICAL RULES FOR GOOGLE SEARCH & ACCURACY:
1. USE LIVE SEARCH: ఈ కంపెనీ యొక్క కచ్చితమైన గత 2-3 సంవత్సరాల పనితీరు (Past Performance), ప్రస్తుత మార్కెట్ పరిస్థితి (Current Status), మరియు లేటెస్ట్ మేనేజ్‌మెంట్ కామెంటరీ (Management Commentary) ని గూగుల్ సెర్చ్ ద్వారా లైవ్ గా వెతికి నిజమైన డేటాను సేకరించు.
2. FUTURE MARKET OUTLOOK: ఈ వార్త ఆధారంగా రాబోయే రోజుల్లో/భవిష్యత్తులో ఈ స్టాక్ లేదా సెక్టార్ గురించి మార్కెట్ (FIIs/DIIs/Big Players) ఎలా ఆలోచిస్తోంది, ఎలాంటి ట్రెండ్ ఉండబోతోంది అనే మార్కెట్ సెంటిమెంట్ అంచనాను కూడా విశ్లేషణలో స్పష్టంగా చేర్చు.
3. NO HALLUCINATION: నీ సొంత తెలివితో లేదా ఊహలతో 40%, 45% లాంటి నంబర్లను లేదా అంచనాలను సృష్టించవద్దు. గూగుల్ సెర్చ్ లో దొరికిన కచ్చితమైన ఫ్యాక్ట్స్ మరియు రిపోర్ట్స్ ఆధారంగానే విశ్లేషణ రాయి.

ఇది సాధారణ కంపెనీ వార్త లేదా చిన్న కదలిక అయితే 'NOT_IMPORTANT' అని రాయి. 
ఒకవేళ ఇది గ్లోబల్ మేక్రో, సెక్టార్ రొటేషన్ లేదా పాలసీలను శాసించగల హై-క్వాలిటీ విషయం అయితే... 
ముందుగా [ONE_LINE] అనే టాగ్ పెట్టి కేవలం ఒకే ఒక్క లైన్ లో క్విక్ విశ్లేషణ రాయి. 
ఆ తర్వాత [DEEP_ANALYSIS] అనే టాగ్ పెట్టి, ఒక బిగ్ ఇన్వెస్టర్ మైండ్‌సెట్ తో దీని వెనుక ఉన్న అసలు కారణం ఏంటి, మార్కెట్ పై దీని దీర్ఘకాలిక ప్రభావం ఎలా ఉంటుంది అనేది చాలా అద్భుతమైన, సుదీర్ఘమైన పూర్తి తెలుగు విశ్లేషణను కింద వివరించు సర్."""
                
                try:
                    # 🔍 గూగుల్ అఫీషియల్ జెమిని క్లయింట్ కి లైవ్ సెర్చ్ టూల్ కనెక్ట్ చేసాం సర్
                    response = client_key1.models.generate_content(
                        model='gemini-2.5-flash', 
                        contents=prompt,
                        config={"tools": [{"google_search": {}}]} # 🔥 ఈ ఒక్క లైన్ జెమినికి లైవ్ ఇంటర్నెట్ పవర్ ఇస్తుంది!
                    )
                    agent_output = response.text.strip()
                except Exception as api_err:
                    
                    err_str = str(api_err)
                    safe_title = clean_for_html(raw_title)
                    safe_source = clean_for_html(source)
                    
                    # 💥 [CRITICAL FIX] API ఫెయిల్ అయినా ఈ వార్తను MongoDB లో వేసేయాలి!
                    # లేకపోతే నెక్స్ట్ లూప్ లో మళ్ళీ జెమిని ని అడిగి 429 రేట్ లిమిట్ తెస్తుంది సర్.
                    if news_collection is not None:
                        try:
                            news_collection.insert_one({
                                "clean_content": current_clean_content,
                                "title": raw_title,
                                "timestamp": datetime.now()
                            })
                        except: pass
                    
                    if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                        error_msg = f"⚠️ <b>[API RATE LIMIT ALERT]</b>\n\n" \
                                    f"❌ <b>ఎర్రర్ 429:</b> బ్యాక్‌గ్రౌండ్ జెమిని డేటా లిమిట్ దాటింది సర్.\n" \
                                    f"🗞️ <b>మిస్సయిన వార్త:</b> {safe_title}\n" \
                                    f"🌐 <b>మూలం:</b> {safe_source}"
                        bot.send_message(YOUR_TELEGRAM_CHAT_ID, error_msg, parse_mode="HTML")
                    elif "503" in err_str or "UNAVAILABLE" in err_str:
                        error_msg = f"⚠️ <b>[SERVER BUSY ALERT]</b>\n\n" \
                                    f"❌ <b>ఎర్రర్ 503:</b> జెమిని సర్వర్ బిజీగా ఉంది సర్.\n" \
                                    f"🗞️ <b>మిస్సయిన వార్త:</b> {safe_title}\n" \
                                    f"🌐 <b>మూలం:</b> {safe_source}"
                        bot.send_message(YOUR_TELEGRAM_CHAT_ID, error_msg, parse_mode="HTML")
                    else:
                        print(f"API Error: {err_str}")
                        report_error_to_telegram(f"Live Research Loop (API Failure)", f"News: {safe_title}\nErr: {err_str}")
                    
                    time.sleep(30)
                    continue
                
                # 💥 [FIX] సక్సెస్ అయి 'NOT_IMPORTANT' వచ్చినా కూడా MongoDB లో వేసి బ్లాక్ చేయాలి సర్
                if "NOT_IMPORTANT" in agent_output:
                    print(f"📉 [AI REJECTED] జెమిని ఈ వార్తను 'NOT_IMPORTANT' అని రిజెక్ట్ చేసింది సర్.")
                    if news_collection is not None:
                        try:
                            news_collection.insert_one({
                                "clean_content": current_clean_content,
                                "title": raw_title,
                                "status": "NOT_IMPORTANT",
                                "timestamp": datetime.now()
                            })
                        except: pass
                    continue

                if "[DEEP_ANALYSIS]" in agent_output:
                    print(f"🚀 [HIGH IMPACT] అద్భుతమైన వార్త దొరికింది! టెలిగ్రామ్‌కు అలర్ట్ జనరేట్ చేస్తున్నాను...")
                    
                    # 💥 [FIX] హై ఇంపాక్ట్ వార్తను కూడా వెంటనే MongoDB లో సేవ్ చేస్తున్నాం సర్
                    if news_collection is not None:
                        try:
                            news_collection.insert_one({
                                "clean_content": current_clean_content,
                                "title": raw_title,
                                "status": "HIGH_IMPACT",
                                "timestamp": datetime.now()
                            })
                        except: pass

                    parts = agent_output.split("[DEEP_ANALYSIS]")
                    one_line_part = parts[0].replace("[ONE_LINE]", "").replace("HIGH_IMPACT", "").strip()
                    deep_analysis_part = parts[1].strip()
                    
                    raw_part1 = deep_analysis_part
                    raw_part2 = ""
                    
                    if len(deep_analysis_part) > 3000:
                        raw_part1 = deep_analysis_part[:3000]
                        raw_part2 = deep_analysis_part[3000:]

                    safe_title = clean_for_html(raw_title)
                    safe_source = clean_for_html(source)
                    safe_one_line = clean_for_html(one_line_part)
                    
                    part1_text = clean_for_html(raw_part1)
                    part2_text = ""
                    
                    if raw_part2:
                        part1_text += "\n\n<b>...(ఇంకా ఉంది సర్, కింద ఉన్న 'Next Part' బటన్ నొక్కండి)...</b>"
                        part2_text = "<b>...(మునుపటి భాగం కొనసాగింపు)...</b>\n\n" + clean_for_html(raw_part2)
                    
                    unique_id = int(time.time() * 1000)
                    msg_id = f"view_{unique_id}"
                    part2_id = f"pt2_{unique_id}"
                    back_id = f"back_{unique_id}"
                    
                    short_telegram_msg = f"📢 <b>రీసెర్ך టీమ్ లైవ్ అలర్ట్</b>\n\n" \
                                         f"🗞️ <b>వార్త శీర్షిక:</b> {safe_title}\n" \
                                         f"🌐 <b>మూలం:</b> {safe_source}\n" \
                                         f"💡 <b>క్విక్ వ్యూ:</b> {safe_one_line}"

                    analysis_vault[msg_id] = {
                        "title": safe_title,
                        "source": safe_source,
                        "part1": part1_text,
                        "part2": part2_text,
                        "original_text": short_telegram_msg,
                        "part2_key": part2_id,
                        "back_key": back_id
                    }
                    analysis_vault[part2_id] = msg_id
                    analysis_vault[back_id] = msg_id
                    
                    markup = InlineKeyboardMarkup()
                    view_btn = InlineKeyboardButton(text="🔎 పూర్తి విశ్లేషణ చదవండి (Read Full View)", callback_data=msg_id)
                    markup.add(view_btn)
                                                                                                      
                    bot.send_message(YOUR_TELEGRAM_CHAT_ID, short_telegram_msg, reply_markup=markup, parse_mode="HTML")
                    print(f"📤 [TELEGRAM SENT] టెలిగ్రామ్‌కు అలర్ట్ విజయవంతంగా పంపబడింది సర్.")
                    time.sleep(2)
                    
                else:
                    print(f"⚠️ [FORMAT MISMATCH] జెమిని నుండి రెస్పాన్స్ వచ్చింది కానీ సరైన టాగ్స్ లేవు.")
                    
            print(f"\n📡📡 నిరంతర నిఘా లూప్ ముగిసింది. మళ్లీ 5 నిమిషాల తర్వాత చెక్ చేస్తుంది సర్...")
            
        except Exception as e:
            print(f"⚠️ [LOOP EXCEPTION] Live Research లూప్‌లో అంతరాయం: {e}")
            report_error_to_telegram("Live Research Main Loop", str(e))
            
        time.sleep(300)

# =====================================================================
# 🚀 మాస్టర్ కమాండ్ సెంటర్
# =====================================================================
if __name__ == "__main__":
    
    print("🧹 Render లో Token Conflict రాకుండా పాత కనెక్షన్‌లను క్లియర్ చేస్తున్నాను సర్...")
    try:
        bot.delete_webhook(drop_pending_updates=True)
        time.sleep(2) 
        print("✅ పాత కనెక్షన్‌లు మరియు పెండింగ్ అప్‌డేట్స్ అన్నీ క్లియర్ అయ్యాయి సర్!")
    except Exception as token_err:
        print(f"⚠️ కనెక్షన్ క్లియర్ చేయడంలో చిన్న ఇబ్బంది: {token_err}")

    start_msg = "🤖 <b>AI స్మార్ట్ MongoDB డ్యూయల్-సిస్టమ్ బాట్ రెడీ సర్!</b>\n\n" \
                "🎯 <b>లాస్-లెస్ మెమొరీ:</b> సర్వర్ రీస్టార్ట్ అయినా పాత వార్తలను MongoDB ఎప్పటికీ మర్చిపోదు!"
    
    print(start_msg)
    try: bot.send_message(YOUR_TELEGRAM_CHAT_ID, start_msg, parse_mode="HTML")
    except: pass
    
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=live_research_surveillance_worker, daemon=True).start()

    @bot.message_handler(commands=['help', 'start'])
    def send_command_list(message):
        try:
            help_text = "📋 <b>AI రీసెర్చ్ బాట్ కమాండ్స్ లిస్ట్ సర్:</b>\n\n" \
                        "కింద ఉన్న పదాల మీద ఒక్కసారి టచ్ చేయండి సర్, ఆటోమేటిక్‌గా కాపీ అవుతుంది:\n\n" \
                        "🌍 <b>మల్టీ-డైమెన్షనల్ మార్కెట్ అప్‌డేట్స్:</b>\n" \
                        "<code>eeroju market updates</code>\n\n" \
                        "🎯 <b>డ్యూయల్ ఆల్ఫా స్టాక్ పిక్స్:</b>\n" \
                        "<code>eeroju stock picks</code>"
            bot.send_message(message.chat.id, help_text, parse_mode="HTML")
        except Exception as e:
            report_error_to_telegram("Command Handler (Start/Help)", str(e))

    @bot.callback_query_handler(func=lambda call: True)
    def callback_listener(call):
        global analysis_vault
        msg_key = call.data
        
        try:
            bot.answer_callback_query(call.id)
        except: pass
            
        try:
            if msg_key in analysis_vault:
                if msg_key.startswith("view_"):
                    vault_data = analysis_vault[msg_key]
                    
                    full_report = f"📊 <b>పూర్తి రీసెర్చ్ నివేదిక - Part 1</b>\n" \
                                  f"🗞 <i>వార్త:</i> {vault_data['title']}\n" \
                                  f"🌐 <i>మూలం:</i> {vault_data['source']}\n" \
                                  f"--------------------------------------------------\n\n" \
                                  f"{vault_data['part1']}"
                    
                    markup = InlineKeyboardMarkup()
                    if vault_data['part2'] != "":
                        next_btn = InlineKeyboardButton(text="➡️ మిగిలిన భాగం (Next Part)", callback_data=vault_data['part2_key'])
                        markup.add(next_btn)
                    back_btn = InlineKeyboardButton(text="⬅️ వెనక్కి వెళ్ళండి (Back to Alert)", callback_data=vault_data['back_key'])
                    markup.add(back_btn)
                    
                    # 💥 [MESSAGE_TOO_LONG FIX] ఒకవేళ పార్ట్-1 టెలిగ్రామ్ లిమిట్ దాటితే ఎడిట్ చేయకుండా కొత్త మెసేజ్ కింద పంపుతుంది సర్
                    try:
                        if len(full_report) <= 4000:
                            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=full_report, reply_markup=markup, parse_mode="HTML")
                        else:
                            # పాత మెసేజ్ డిలీట్ చేసి కొత్తగా ముక్కలుగా పంపుతుంది
                            bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
                            send_split_message(call.message.chat.id, full_report)
                            # కింద కంట్రోల్ బటన్స్ విడిగా పంపుతుంది
                            bot.send_message(call.message.chat.id, "<b>కంట్రోల్ ఆప్షన్స్:</b>", reply_markup=markup, parse_mode="HTML")
                    except:
                        try: bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=full_report, reply_markup=markup, parse_mode=None)
                        except: pass

                elif msg_key.startswith("pt2_"):
                    view_key = analysis_vault[msg_key]
                    vault_data = analysis_vault[view_key]
                    
                    part2_report = f"📊 <b>పూర్తి రీసెర్చ్ నివేదిక - Part 2 (చివరి భాగం)</b>\n" \
                                   f"🗞 <i>వార్త:</i> {vault_data['title']}\n" \
                                   f"--------------------------------------------------\n\n" \
                                   f"{vault_data['part2']}"
                    
                    markup = InlineKeyboardMarkup()
                    first_part_btn = InlineKeyboardButton(text="⬅️ మొదటి భాగం చదవండి (Part 1)", callback_data=view_key)
                    back_btn = InlineKeyboardButton(text="⬅️ వెనక్కి వెళ్ళండి (Back to Alert)", callback_data=vault_data['back_key'])
                    markup.add(first_part_btn, back_btn)
                    
                    try:
                        if len(part2_report) <= 4000:
                            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=part2_report, reply_markup=markup, parse_mode="HTML")
                        else:
                            bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
                            send_split_message(call.message.chat.id, part2_report)
                            bot.send_message(call.message.chat.id, "<b>కంట్రోల్ ఆప్షన్స్:</b>", reply_markup=markup, parse_mode="HTML")
                    except:
                        try: bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=part2_report, reply_markup=markup, parse_mode=None)
                        except: pass

                elif msg_key.startswith("back_"):
                    view_key = analysis_vault[msg_key]
                    vault_data = analysis_vault[view_key]
                    
                    original_markup = InlineKeyboardMarkup()
                    view_btn = InlineKeyboardButton(text="🔎 పూర్తి విశ్లేషణ చదవండి (Read Full View)", callback_data=view_key)
                    original_markup.add(view_btn)
                    
                    try:
                        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=vault_data['original_text'], reply_markup=original_markup, parse_mode="HTML")
                    except:
                        try: bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=vault_data['original_text'], reply_markup=original_markup, parse_mode=None)
                        except: pass
            else:
                bot.send_message(call.message.chat.id, "❌ <b>ఈ విశ్లేషణ పాతదవడం వల్ల మెమొరీ నుండి డిలీట్ అయింది సర్.</b>", parse_mode="HTML")
        except Exception as e:
            report_error_to_telegram("Callback Listener Main Fix", str(e))
            
    # చాట్ ప్రశ్నల హ్యాండ్లర్
    @bot.message_handler(func=lambda message: True)
    def handle_user_research_query(message):
        user_query = message.text.lower().strip()
        
        # --- ఆ క్షణంలో ఉన్న తాజా లైవ్ మార్కెట్ డేటాను ఆర్‌ఎస్‌ఎస్ ఫీడ్స్ నుండి సేకరిస్తున్నాం సర్ ---
        live_data_summary = ""
        try:
            macro_feeds = [
                ("ET_Markets", "https://economictimes.indiatimes.com/markets/rssfeeds/2146842.cms"),
                ("Moneycontrol", "https://www.moneycontrol.com/rss/economy.xml"),
                ("Investing", "https://in.investing.com/rss/news_286.rss")
            ]
            headers = {"User-Agent": "Mozilla/5.0"}
            feed_texts = []
            for name, url in macro_feeds:
                try:
                    res = requests.get(url, headers=headers, timeout=5)
                    if res.status_code == 200:
                        root = ET.fromstring(res.content)
                        for item in root.findall('.//item')[:6]:
                            title = item.find('title').text or ""
                            desc = item.find('description').text or ""
                            clean_desc = re.sub('<[^<]+?>', '', desc)
                            feed_texts.append(f"[{name}] {title} - {clean_desc}")
                except: continue
            live_data_summary = "\n".join(feed_texts[:15])
        except Exception as data_err:
            print(f"Error fetching live data for chat: {data_err}")

        # 🌍 కమాండ్ 1: మార్కెట్ అప్‌డేట్స్ (బగ్ ఫిక్స్ వెర్షన్)
        if "market updates" in user_query or "market visheshalu" in user_query:
            bot.reply_to(message, f"🌍 సర్, మన మాస్టర్ మైండ్ AI మార్కెట్ & సర్వైలెన్స్ డేటాను విశ్లేషిస్తోంది. ఒక్క నిమిషం సర్...")
            
            # 📊 [FIX 1] మొదట లైవ్ మార్కెట్ నెంబర్ల డేటాను ఇక్కడికి రప్పించాలి సర్!
            actual_live_numbers = get_live_market_data()
            
            # 📊 [FIX 2] ఒకవేళ ప్రొవిజనల్ FII/DII డేటా కూడా అందుబాటులో ఉంటే తెచ్చుకోవాలి
            fii_dii_summary = get_fii_dii_data()
            
            market_prompt = f"""You are a World-Class Chief Investment Officer, Veteran Professional Trader, and Factual Financial Journalist. Today is {time.strftime('%Y-%m-%d')}.

CRITICAL: HERE IS THE RAW FACTUAL LIVE DATA AND INDEX LEVELS TO USE:
\"\"\"
{actual_live_numbers}
{fii_dii_summary}
\"\"\"

Analyze this supplementary NEWS SUMMARY captured right now:
\"\"\"
{live_data_summary}
\"\"\"

CRITICAL RULES FOR ACCURACY:
1. NO HALLUCINATION: Write ONLY verified facts and numbers from the context. If any index or factor is missing, display '0.0' or 'Not Available'. Do not guess or invent data.
2. ABSOLUTE HONESTY: State the exact market reality. If the market is bad, say it is bad; if good, say it is good, along with exact structural reasons.

FORMATTING RULES FOR TELEGRAM:
- You must use REAL empty lines by pressing Enter, do NOT write text like "<Two blank lines>" or "<Line Break>".
- Leave TWO blank lines (Double Enter) between major sections to ensure a BIG visual gap.
- Leave ONE blank line (Single Enter) between sub-points to ensure a SMALL visual gap.
- Never merge a section header and its details on the same line.

TASK:
Develop a highly professional, scannable Market Intelligence Report in clear Telugu. Think like a top-tier hedge fund manager. Organize it logically into this exact template layout:

🚨 **ఇన్‌స్టిట్యూషనల్ మార్కెట్ మాస్టర్ మైండ్ రిపోర్ట్** 🚨
📅 **తేదీ:** {time.strftime('%Y-%m-%d')}


📊 **భాగం 1: కచ్చితమైన ఇండెక్స్ నెంబర్లు (EXACT INDEX NUMBERS)**

• **NIFTY 50:** [Level] ([%Change])
  - ఓపెన్: [Price]

• **SENSEX:** [Level] ([%Change])
  - ఓపెన్: [Price]

• **BANK NIFTY:** [Level] ([%Change])
  - ఓపెన్: [Price]

• **NIFTY IT:** [Level] ([%Change])

• **NIFTY METAL:** [Level] ([%Change])

• **NIFTY FMCG:** [Level] ([%Change])


🇮🇳 **భాగం 2: జాతీయ పరిణామాలు & देशీయ వార్తలు (NATIONAL CONTEXT & INTRA-DAY NEWS)**

• **ఉదయం నుండి సాయంత్రం వరకు మార్కెట్ ప్రయాణం:**
[Explain actual day movement using RSS headlines. Is it good or bad? Tell the hard truth.]

• **మార్కెట్ ఇలా ఉండటానికి గల కచ్చితమైన దేశీయ कारणాలు:**
[List exact domestic triggers, economic data, or policy changes from the feed.]


🌍 **భాగం 3: అంతర్జాతీయ పరిణామాలు & గ్లోబల్ మ్యాక్రో ఫ్యాక్ట్స్ (GLOBAL DEVELOPMENTS & IMPACT)**

• **ప్రధాన అంతర్జాతీయ పరిణామాలు:**
[Explain global macro events, US Fed/interest rate cues, geopolitical triggers from the news.]

• **గ్లోబల్ మ్యాక్రో నెంబర్స్ & ఇంపాక్ట్:**
- US 10Y Bond Yield: [Level from summary]
- DXY (Dollar Index): [Level] | USDINR: [Level]
- Brent Crude: [Level]
- Nasdaq: [Level]

• **ఫండ్ ప్రవాహాలపై ప్రభావం:**
[Explain exactly how these global numbers are shifting FII flows and Indian equity markets.]


🛡️ **భాగం 4: ఎక్స్ఛేంజ్ సర్వైలెన్స్ & రెగ్యులేటరీ అప్‌డేట్స్ (EXCHANGE SURVEILLANCE & ACTIONS)**

• **డైలీ సర్వైలెన్స్ నివేదిక (ASM / GSM / ESM ట్రేడింగ్ అప్‌డేట్స్):**
[Based on your institutional corporate knowledge and today's notices, explain why stock exchanges put certain high-risk/volatile stocks under ASM (Additional Surveillance Measure), GSM, or ESM frameworks. Highlight what this means for margins (minimum 50% or 100% requirement), trade-for-trade shifts, or price bands (like 2% limitations). If no specific stocks are mentioned in the immediate feed, explain the core risk framework traders must watch today to protect capital.]


🏢 **భాగం 5: కార్పొరేట్ వార్తలు & సెక్టార్ వైజ్ విశ్లేషణ (CORPORATE ACTIONS & SECTOR INSIGHTS)**

• [Sector Name 1]: [Company corporate news, earnings, or orders mentioned in RSS]
- **ఇన్‌సైట్ (Insight):** [What this means for the stock/sector logically]

• [Sector Name 2]: [Another sector news]
- **ఇన్‌సైట్ (Insight):** [What this means logically]


🧠 **భాగం 6: సీనియర్ అనలిస్ట్ విశ్లేషణ & ట్రెండ్ ముగింపు (PROFESSIONAL SYNTHESIS & OUTLOOK)**

• **ఒక ప్రొఫెషనల్ ట్రేడర్/ఇన్వెస్టర్ ఆలోచనా విధానం:**
[Combine all national, international, and index facts into a professional mastermind evaluation.]

• **మార్కెట్ ముగింపు & రాబోయే రోజుల్లో కచ్చితమైన ట్రెండ్:**
[Factual, clear conclusion on market direction based strictly on current context. No fake predictions.]

Generate Master Report Now:"""
            
            try:
                response = client_key2.models.generate_content(model='gemini-2.5-flash', contents=market_prompt)
                send_split_message(message.chat.id, response.text)
            except Exception as e:
                err_msg = str(e)
                if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                    bot.send_message(message.chat.id, "⚠️ **ఎర్రర్ 429: జెమిని ఏపిఐ డేటా లిమిట్ దాటింది సర్! కొద్దిసేపు ఆగి ప్రయత్నించండి.**")
                elif "503" in err_msg or "UNAVAILABLE" in err_msg:
                    bot.send_message(message.chat.id, "⚠️ **ఎర్రర్ 503: జెమిని సర్వర్ ప్రస్తుతం చాలా బిజీగా ఉంది సర్! ప్లీజ్ ట్రై అగైన్ లేటర్.**")
                else:
                    bot.send_message(message.chat.id, f"❌ **మార్కెట్ రీసెర్చ్ లో చిన్న అంతరాయం సర్. మళ్లీ ట్రై చేయండి.**")
                
        # 🎯 కమాండ్ 2: స్టాక్ పిక్స్
        elif "stock picks" in user_query or "stocks selection" in user_query:
            bot.reply_to(message, f"🎯 సర్, మన పోర్ట్‌ఫోలియో మేనేజర్ AI రియల్ డేటా మరియు లోతైన విశ్లేషణ ఆధారంగా బెస్ట్ స్టాక్స్ ఎంచుకుంటోంది. ఒక్క నిమిషం సర్...")
            
            dual_stock_prompt = f"""You are a SEBI-Registered Lead Financial Analyst, Top-Tier Hedge Fund Manager, and Master Mind Professional Trader. Today is {time.strftime('%Y-%m-%d')}.

Analyze the live market setup and historical corporate data repository:
\"\"\"
{live_data_summary}
\"\"\"

CRITICAL REQUISITE FROM THE USER (ACT AS AN INSTITUTIONAL MASTER MIND):
The user demands a 100% rigorous, comprehensive, fact-based investment evaluation. Since you are billion times more powerful with data processing, you must provide a RAZOR-SHARP INSTITUTIONAL EVALUATION (పదునైన లోతైన విశ్లేషణ) for each stock. Explain the deeply buried market mechanics, structural advantages, and precise triggers that separate these 2 stocks from ordinary market names. Do NOT write generic text. 

💥 SYSTEM EMERGENCY RULE: 
If there are NO highly robust, fundamentally strong, top-tier quality stocks available in the market context today based on facts, do NOT force or create a fake report. Instead, strictly output ONLY this exact sentence in Telugu and nothing else: 'సర్, ఈరోజు అంతటి బలమైన, తిరుగులేని వృద్ధి గల స్టాక్ ఏదీ రీసెర్చ్ టీమ్‌కు దొరకలేదు సర్'.

STRICT TELEGRAM FORMATTING:
- Leave TWO blank lines (Double Enter) between Stock 1 and Stock 2 (BIG GAP).
- Leave ONE blank line (Single Enter) between sub-parameters (SMALL GAP).
- Never merge titles and data text on the same line.

TASK: Select exactly 2 high-quality distinct Indian stocks based on today's realities and provide a deep-dive institutional research report in clear Telugu:

🎯 **నిజమైన డేటా ఆధారిత ఇన్‌స్టిట్యూషనల్ ఆల్ఫా పిక్స్** 🎯


💎 **స్టాక్ 1: పక్కా ఫండమెంటల్ & ఫైనాన్షియల్ పవర్ హౌస్ (CORE CONVICTION)**

• **కంపెనీ పేరు & టిక్కర్:** [Real Stock Name & Ticker]

• **🔥 అసలు ఈ స్టాక్‌ను ఈరోజే ఎంచుకోవడానికి గల కచ్చితమైన కారణం (CORE SELECTION REASON):**
[Explain here like a Master Mind CIO exactly why this stock is chosen today. Connect its valuation, macro setups, or market resilience directly to today's market situation so the user can analyze and take a firm decision.]

• **🧠 AI పదునైన లోతైన విశ్లేషణ & కోర్ ఎడ్జ్ (SHARP INSTITUTIONAL INSIGHT):**
[Utilize your massive computing database intelligence to give a razor-sharp, ultra-deep 3-4 line master analysis here in Telugu. Explain the deeply buried margin stability, pricing power, competitive moat, and exact long-term investment matrix that ordinary investors miss.]

• **కోర్ ఇన్వెస్ట్‌మెంట్ థీసిస్:** [Deep fundamental business model strength in 2 lines]

• **కీలక ఫండమెంటల్ గణాంకాలు (CORE NUMBERS):**
  - మార్కెట్ క్యాప్ (M-Cap): [Real Value] | ప్రస్తుత ధర (CMP): [Price]
  - P/E రేషియో: [Real P/E] | P/B రేషియో: [Real P/B] | PEG రేషియో: [Real PEG]
  - సేల్స్ గ్రోత్ (Sales Growth %): [3-5 Yr CAGR profiling]
  - ప్రాఫిట్ గ్రోత్ (Profit Growth %): [3-5 Yr CAGR or Recent PAT trends]
  - ఆపరేటింగ్ & నెట్ ప్రాఫిట్ మార్జిన్స్ (Margins %): [Operating Margin % / Net Margin %]
  - ROE % & ROCE %: [ROE % / ROCE % from active database]
  - డెట్-టు-ఈక్విటీ (Debt-to-Equity): [Exact leverage ratio]

• **షేర్‌హోల్డింగ్ ప్యాటర్న్ & ప్లెడ్జింగ్ (SHAREHOLDING STRUCTURE):**
  - ప్రమోటర్లు (Promoters %): [Real %] | FII %: [Real %] | DII %: [Real %] | Public %: [Real %]
  - వాటాల తాకట్టు (Pledging %): [Exact Pledging % or state 'Clean/Zero']

• **మేనేజ్‌మెంట్ కామెంటరీ & ఇన్‌స్టిట్యూషనల్ వ్యూ:**
  - యాజమాన్య వ్యూహం: [Latest earnings call commentary updates]
  - బ్రోకరేజ్ / రీసెర్చ్ రిపోర్ట్స్ అప్‌గ్రేడ్స్: [Recent targets or rating revisions]

• **టెక్నికల్ స్ట్రక్చర్ & ఎంట్రీ జోన్స్:** [Factual support/resistance levels from charts]


🚀 **స్టాక్ 2: హిడెన్ ఫ్యూチャー గ్రోత్ & టర్నరౌండ్ పిక్ (FUTURE CATALYST)**

• **కంపెనీ పేరు & టిక్కర్:** [Real Stock Name & Ticker]

• **🔥 అసలు ఈ స్టాక్‌ను ఈరోజే ఎంచుకోవడానికి గల కచ్చితమైన కారణం (CORE SELECTION REASON):**
[Detail the exact turnaround trigger, volume breakout, or sudden policy push that makes this stock highly lucrative right now. Give deep analytical clarity.]

• **🧠 AI పదునైన లోతైన విశ్లేషణ & కోర్ ఎడ్జ్ (SHARP INSTITUTIONAL INSIGHT):**
[Provide a razor-sharp data-driven institutional depth synthesis here in Telugu. Detail why this turnaround or growth under-the-radar setup has a massive probability of outperforming the benchmark index in the coming quarters based on institutional data tracking.]

• **(A) ఫండమెంటల్స్ & ఫైనాన్షియల్ బలం (CORE FINANCES):**
  - M-Cap & CMP: [Details] | P/E & P/B: [Details]
  - సేల్స్, ప్రాఫిట్ & మార్జిన్స్ ట్రెండ్: [Deep operational numbers check]
  - ROE % & ROCE % Profile: [Database numbers]
  - అప్పు (Debt-to-Equity): [Ratio]

• **(B) షేర్‌హోల్డింగ్ ప్యాటర్న్ & ప్లెడ్జింగ్:**
  - ప్రమోటర్ %, FII %, DII %, Public %: [Exact break-up]
  - ప్లెడ్జింగ్ (Pledging %): [Exact or Zero]

• **(C) మేనేజ్‌మెంట్ కామెంటరీ & రీసెర్చ్ రిపోర్ట్స్ ఇన్‌సైట్స్:**
  - యాజమాన్య వ్యూహం: [Future expansion and execution details]
  - ఇన్‌స్టిట్యూషన్ల అంచనాలు: [Target prices and upgrades/downgrades context]

• **(D) ఫ్యూチャー కాటలిสต์ & సెక్టార్ డిమాండ్ (INDUSTRY TAILWINDS):**
  - భవిష్యత్ ఆర్డర్లు/గ్రోత్ ట్రిగ్గర్స్: [Government policies, capex, or new order book catalysts]

• **(E) టెక్నికల్స్ & ఎంట్రీ/ఎగ్జిట్ ప్లాన్:** [Breakout charts structure, major supports and resistance analysis]

Begin your high-end institutional research report now:"""
            
            try:
                response = client_key2.models.generate_content(model='gemini-2.5-flash', contents=dual_stock_prompt)
                send_split_message(message.chat.id, response.text)
            except Exception as e:
                err_msg = str(e)
                if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                    bot.send_message(message.chat.id, "⚠️ **ఎర్రర్ 429: జెమిని ఏపిఐ డేటా లిమిట్ దాటింది సర్! కొద్దిసేపు ఆగి ప్రయత్నించండి.**")
                elif "503" in err_msg or "UNAVAILABLE" in err_msg:
                    bot.send_message(message.chat.id, "⚠️ **ఎర్రర్ 503: జెమిని సర్వర్ ప్రస్తుతం చాలా బిజీగా ఉంది సర్! ప్లీజ్ ట్రై అగైన్ లేటర్.**")
                else:
                    bot.send_message(message.chat.id, f"❌ **స్టాక్ రీసెర్చ్ లో చిన్న అంతరాయం సర్. మళ్లీ ట్రై చేయండి.**")

        # సాధారణ చాట్ ప్రశ్నలు
        else:
            bot.reply_to(message, f"🧠 ఓకే సర్, మీ ప్రశ్నకు సమాధానాన్ని మన రీసెర్చ్ టీమ్ సిద్ధం చేస్తోంది...")
            try:
                response = client_key2.models.generate_content(model='gemini-2.5-flash', contents=message.text)
                send_split_message(message.chat.id, response.text)
            except Exception as e:
                err_msg = str(e)
                if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                    bot.send_message(message.chat.id, "⚠️ **ఎర్రర్ 429: జెమిని ఏపిఐ డేటా లిమిట్ దాటింది సర్!**")
                elif "503" in err_msg or "UNAVAILABLE" in err_msg:
                    bot.send_message(message.chat.id, "⚠️ **ఎర్రర్ 503: జెమిని సర్వర్ బిజీగా ఉంది సర్!**")
                else:
                    bot.send_message(message.chat.id, f"❌ **చిన్న సాంకేతిక లోపం సర్. మళ్లీ ప్రయత్నించండి.**")
                report_error_to_telegram("User Query Handler", str(e))

    # టెలిగ్రామ్ బోట్ ఇన్ఫినిటీ పోలింగ్ స్టార్ట్
    bot.infinity_polling()
