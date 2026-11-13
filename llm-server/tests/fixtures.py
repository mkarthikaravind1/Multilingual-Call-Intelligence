"""
Test Fixtures: Realistic Automotive Service-Centre Call Transcripts
Languages: English, Tamil, and Tanglish (Tamil code-mixed with English)
Format: Numbered lines "[1] ICR: ..." / "[2] CUSTOMER: ..."
"""

SYSTEM_INSTRUCTION = """You are an AI assistant analyzing telephone calls for an automotive service centre in Tamil Nadu, India.
Analyze the provided transcript of a phone conversation between an Inbound Customer Representative (ICR) and a customer.
Return your response strictly as a JSON object with the following schema:
{
  "complaint_categories": ["string", ...],
  "customer_mood": {
    "label": "frustrated" | "angry" | "neutral" | "satisfied" | "concerned",
    "confidence": float (between 0.0 and 1.0),
    "evidence": "quote or observation from transcript"
  },
  "escalate": boolean,
  "suggested_next_questions": ["string in customer's preferred language", ...],
  "summary": "concise 2-sentence summary of the conversation"
}
Output valid JSON only. Do not wrap in markdown backticks or commentary.
"""

CALL_TRANSCRIPTS = [
    # 1. English - Brake Noise & Delayed Vehicle Delivery
    {
        "id": "call_001_english_brake_delivery",
        "language": "English",
        "transcript": """[1] ICR: Good morning, Thank you for calling Zenith Hyundai Service Centre, Chennai. My name is Karthik. How may I assist you today?
[2] CUSTOMER: Hello Karthik. I gave my Creta for the 30,000 km paid service three days ago. Your service advisor promised delivery yesterday evening by 5 PM. Nobody called me, and when I arrived, the car wasn't ready!
[3] ICR: I am extremely sorry for the inconvenience, sir. Let me pull up your job card. Could you please share your vehicle registration number?
[4] CUSTOMER: It is TN 09 CB 4412. Also, before giving the car, I complained about a sharp squeaking noise from the front left brake pad while applying brakes at slow speeds. Yesterday the advisor casually told me parts were out of stock. Why wasn't I informed earlier?
[5] ICR: I completely understand your frustration, sir. Looking at the system, the front brake pads were received this morning and the technician is currently fitting them. The car will undergo final wash by 2:30 PM today.
[6] CUSTOMER: Look, I have an urgent drive to Coimbatore tonight. If the car is not handed over to me in clean condition by 3 PM, I will escalate this to your Territory Service Manager.
[7] ICR: Understood, sir. I am marking this job card as High Priority right away. I will personally supervise the quality check and ensure the advisor calls you with a gate pass before 2:45 PM."""
    },

    # 2. Tamil - Engine Overheating & Oil Leakage
    {
        "id": "call_002_tamil_engine_overheating",
        "language": "Tamil",
        "transcript": """[1] ICR: வணக்கம், கேபிஎன் மாருதி சர்வீஸ் சென்டர் கோயம்புத்தூர். என் பெயர் பிரியா. உங்களுக்கு நான் எப்படி உதவ முடியும்?
[2] CUSTOMER: மேடம், நான் போன வாரம் தான் உங்க சென்டர்ல என் ஸ்விப்ட் காரை ஃபுல் சர்வீஸ் பண்ணி டெலிவரி எடுத்தேன். இப்போ ஹைவேல போகும்போது இன்ஜின்ல இருந்து பயங்கர புகை வருது, டெம்பரேச்சர் இண்டிகேட்டர் ரெட் லைட் எரியுது!
[3] ICR: சார், தயவுசெய்து காரை உடனே ஓரமா நிறுத்தி இன்ஜினை ஆஃப் பண்ணிடுங்க. நீங்க இப்போ பாதுகாப்பான இடத்துல இருக்கீங்களா?
[4] CUSTOMER: ஆமா, ஓரமா தான் நிறுத்தி இருக்கேன். ஆனா காரோட அடி பக்கத்துல இருந்து ஆயில் சொட்டு சொட்டா ஒழுகுது. சர்வீஸ் பண்ணி மூணு நாள்ல இப்படி ஆனா என்ன அர்த்தம்? நீங்க சரியா ஆயில் ஃபில்டர் மாட்டலையா? ரோட்ல குடும்பத்தோட நிக்கிறேன்!
[5] ICR: கவலைப்படாதீங்க சார். உங்க சிரமத்துக்கு நாங்க ரொம்ப வருந்துகிறோம். உங்க கார் நம்பர் சொல்ல முடியுமா? எங்க ரோட்-சைடு அசிஸ்டன்ஸ் (RSA) டீமை உடனே அனுப்பி டோயிங் வண்டி ஏற்பாடு பண்றேன்.
[6] CUSTOMER: நம்பர் TN 38 BJ 8910. அவிநாசி பைபாஸ் பக்கத்துல நிக்கிறோம். சீக்கிரம் யாரையாவது அனுப்புங்க. இதுக்கு உங்க சர்வீஸ் சென்டர் தான் முழு பொறுப்பு!
[7] ICR: நிச்சயமாக சார், RSA டீமுக்கு உடனடி லொகேஷன் மெசேஜ் அனுப்பியிருக்கிறேன். அடுத்த 25 நிமிடங்களில் அவசர உதவி வாகனம் உங்களை வந்தடையும்."""
    },

    # 3. Tanglish - AC Cooling Failure & Dispute over Estimate vs Invoice
    {
        "id": "call_003_tanglish_ac_billing_dispute",
        "language": "Tanglish",
        "transcript": """[1] ICR: Good afternoon, Supreme Tata Motors Madurai. Naan Ramesh pesuren, sollunga sir.
[2] CUSTOMER: Ramesh, unga service advisor Anand kitta pesanum. Last week Harrier service kuduthen. AC cooling issue nu sonnen. Avaru estimate Rs. 4,500 gas top-up and filter change nu sonnaru.
[3] ICR: Yes sir, Anand ippo floor-la irukaaru. Naan system check panren. What is your vehicle number sir?
[4] CUSTOMER: TN 58 AK 1102. Bill vandhu Rs. 11,800 nu potirukanga! Compressor coil replacement charges add panirukanga without taking my approval on phone. Edhuku approval illama spare mathuneenga?
[5] ICR: Sir, Job card details la inspection panna appo coil weak-ah irundhuchu nu technician mention panirukaaru. Aana approval call update aagala.
[6] CUSTOMER: That is your internal fault! Naan approve pannadha bill-ku pay panna maaten. Moreover AC innum proper cool aagala. Romba warm air dhaan varudhu. Service advisor phone attend panna maatengraru!
[7] ICR: Romba sorry sir. Approval call record illama bill pottadhu mistake dhaan. Naan indha call-ah Customer Relations Manager Mr. Senthil-ku transfer panren. Bill revise panni cooling check panna technician-ai unga veetukke anupuroam."""
    },

    # 4. Tamil - Clutch Hardness & Mileage Drop
    {
        "id": "call_004_tamil_clutch_mileage",
        "language": "Tamil",
        "transcript": """[1] ICR: வணக்கம், விநாயகா மஹிந்திரா சேலம். நான் சத்யா பேசுகிறேன்.
[2] CUSTOMER: வணக்கம் மேடம், என் பொலிரோ வண்டி ஓட்டும் போது கிளட்ச் பெடல் ரொம்ப டைட்டா ஹார்டா இருக்கு. கியர் மாத்துறதுக்குள்ள கால் வலிக்குது.
[3] ICR: சரிங்க சார், வண்டி வாங்கி எத்தனை வருஷம் ஆகுது? மொத்தம் எத்தனை கிலோமீட்டர் ஓடியிருக்கு சார்?
[4] CUSTOMER: ரெண்டு வருஷம் ஆச்சு, 45,000 கிலோமீட்டர் ஓடியிருக்கு. முன்னாடி மைலேஜ் 16 குடுத்துட்டு இருந்தது, இப்போ 11 கூட வர மாட்டேங்குது. கிளட்ச் பிளேட் தேஞ்சு போச்சா?
[5] ICR: கிளட்ச் கேபிள் அல்லது பிரஷர் பிளேட் தேய்மானம் அடைந்திருக்க வாய்ப்பு இருக்கு சார். கிளட்ச் ஸ்லிப் ஆனா மைலேஜ் குறைய வாய்ப்புண்டு.
[6] CUSTOMER: நாளைக்கு காலைல 9 மணிக்கு வண்டியை செக் பண்ண எடுத்துட்டு வரவா? அதே நாள் சாயங்காலத்துக்குள்ள வேலை முடிஞ்சிடுமா?
[7] ICR: கண்டிப்பா சார், நாளை காலை 9:30 மணிக்கு அப்பாயிண்ட்மெண்ட் புக் பண்ணியிருக்கிறேன். இன்ஸ்பெக்ஷன் பண்ணிட்டு மதியத்துக்குள்ள சரியான காஸ்ட் மற்றும் டெலிவரி நேரம் சொல்லிடலாம்."""
    },

    # 5. Tanglish - Periodic Maintenance & Doorstep Pickup Request
    {
        "id": "call_005_tanglish_service_pickup",
        "language": "Tanglish",
        "transcript": """[1] ICR: Hello, Royal Enfield Service Hub, Tirunelveli. How can I help you today?
[2] CUSTOMER: Hi brother, en Hunter 350-ku second free service schedule pannanum. Odo reading 4,800 km aachu.
[3] ICR: Sure sir! Indha week Thursday or Friday ungalukku convenient-ah irukuma?
[4] CUSTOMER: Enakku office time-la vara mudiyadhu. Unga team doorstep pickup and drop arrange panna mudiyuma from Palayamkottai? Extra charge evalo aagum?
[5] ICR: Definitely sir. 10 km radius-la doorstep pickup free for periodic maintenance. Oil change, chain lubing, and general water wash ellam 4 hours-la mudinjidum.
[6] CUSTOMER: Super. Also, extended warranty 4th year and 5th year add panna enna process nu konjam sollunga.
[7] ICR: Pickup driver unga kitta RSA and Extended Warranty brochure kudupaaru sir. Online payment link SMS panren. Friday morning 8:30 AM pickup confirm pannikalam."""
    }
]


def make_chat_payload(transcript_item, model="openai/gpt-oss-20b"):
    """Creates OpenAI-compatible chat completion payload."""
    user_prompt = f"""Language: {transcript_item['language']}
Transcript:
{transcript_item['transcript']}

Extract the complaint categories, customer mood, escalation decision, suggested next questions, and post-call summary strictly as valid JSON."""

    return {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_INSTRUCTION},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.1,
        "max_tokens": 500,
        "reasoning_effort": "low"
    }
