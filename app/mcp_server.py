"""MCP server providing travel destination research tools.

Run standalone:  python -m app.mcp_server
Used by the Zava travel agent via stdio transport.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("zava-travel-research")

# ---------------------------------------------------------------------------
# Deterministic travel advisory data
# ---------------------------------------------------------------------------
TRAVEL_ADVISORIES: dict[str, dict] = {
    "paris": {
        "destination": "Paris",
        "country": "France",
        "visa_required": False,
        "visa_notes": "US citizens: visa-free for up to 90 days in the Schengen Area.",
        "safety_level": "moderate",
        "safety_notes": "Pickpocketing common near tourist sites. Avoid dark alleys at night.",
        "currency": "EUR (Euro)",
        "timezone": "CET (UTC+1)",
        "power_plug": "Type C/E (230V)",
        "emergency_number": "112",
        "tap_water_safe": True,
        "best_transport": "Metro (RATP) — buy a carnet of 10 tickets for savings.",
    },
    "tokyo": {
        "destination": "Tokyo",
        "country": "Japan",
        "visa_required": False,
        "visa_notes": "US citizens: visa-free for up to 90 days for tourism.",
        "safety_level": "very_safe",
        "safety_notes": "One of the safest major cities. Earthquakes possible — know exit routes.",
        "currency": "JPY (Yen)",
        "timezone": "JST (UTC+9)",
        "power_plug": "Type A/B (100V)",
        "emergency_number": "110 (police) / 119 (fire/ambulance)",
        "tap_water_safe": True,
        "best_transport": "Suica/Pasmo IC card for trains, metro, and buses.",
    },
    "london": {
        "destination": "London",
        "country": "United Kingdom",
        "visa_required": False,
        "visa_notes": "US citizens: visa-free for up to 6 months for tourism.",
        "safety_level": "safe",
        "safety_notes": "Generally safe. Be aware of pickpockets on the Tube.",
        "currency": "GBP (Pound Sterling)",
        "timezone": "GMT (UTC+0) / BST (UTC+1 in summer)",
        "power_plug": "Type G (230V)",
        "emergency_number": "999",
        "tap_water_safe": True,
        "best_transport": "Oyster card or contactless for Tube, buses, and Overground.",
    },
    "cancun": {
        "destination": "Cancún",
        "country": "Mexico",
        "visa_required": False,
        "visa_notes": "US citizens: visa-free for up to 180 days. FMM form required.",
        "safety_level": "moderate",
        "safety_notes": "Hotel zone is safe. Avoid venturing into unfamiliar areas at night.",
        "currency": "MXN (Peso) — USD widely accepted in tourist areas",
        "timezone": "EST (UTC-5)",
        "power_plug": "Type A/B (127V)",
        "emergency_number": "911",
        "tap_water_safe": False,
        "best_transport": "ADO buses or hotel shuttle. Negotiate taxi fares in advance.",
    },
    "bali": {
        "destination": "Bali",
        "country": "Indonesia",
        "visa_required": True,
        "visa_notes": "US citizens: visa on arrival (30 days, ~$35 USD). Extendable once.",
        "safety_level": "safe",
        "safety_notes": "Watch for motorbike traffic. Strong ocean currents at some beaches.",
        "currency": "IDR (Rupiah)",
        "timezone": "WITA (UTC+8)",
        "power_plug": "Type C/F (230V)",
        "emergency_number": "112",
        "tap_water_safe": False,
        "best_transport": "Grab (ride-hailing app) or rent a scooter with international license.",
    },
    "new york": {
        "destination": "New York",
        "country": "United States",
        "visa_required": False,
        "visa_notes": "Domestic travel — no visa needed for US citizens.",
        "safety_level": "safe",
        "safety_notes": "Stay aware in crowded areas. Avoid isolated subway stations late at night.",
        "currency": "USD (US Dollar)",
        "timezone": "EST (UTC-5) / EDT (UTC-4 in summer)",
        "power_plug": "Type A/B (120V)",
        "emergency_number": "911",
        "tap_water_safe": True,
        "best_transport": "MetroCard for subway and buses. Walk in Manhattan.",
    },
    "barcelona": {
        "destination": "Barcelona",
        "country": "Spain",
        "visa_required": False,
        "visa_notes": "US citizens: visa-free for up to 90 days in the Schengen Area.",
        "safety_level": "moderate",
        "safety_notes": "High pickpocket risk on Las Ramblas and in metro. Use money belts.",
        "currency": "EUR (Euro)",
        "timezone": "CET (UTC+1)",
        "power_plug": "Type C/F (230V)",
        "emergency_number": "112",
        "tap_water_safe": True,
        "best_transport": "T-Casual card (10 trips) for metro, bus, and tram.",
    },
    "seattle": {
        "destination": "Seattle",
        "country": "United States",
        "visa_required": False,
        "visa_notes": "Domestic travel — no visa needed for US citizens.",
        "safety_level": "safe",
        "safety_notes": "Generally safe. Some areas downtown can be rough after dark.",
        "currency": "USD (US Dollar)",
        "timezone": "PST (UTC-8) / PDT (UTC-7 in summer)",
        "power_plug": "Type A/B (120V)",
        "emergency_number": "911",
        "tap_water_safe": True,
        "best_transport": "ORCA card for Link Light Rail, buses, and ferries.",
    },
    "rome": {
        "destination": "Rome",
        "country": "Italy",
        "visa_required": False,
        "visa_notes": "US citizens: visa-free for up to 90 days in the Schengen Area.",
        "safety_level": "moderate",
        "safety_notes": "Beware of pickpockets near the Colosseum and on buses. Watch for scams.",
        "currency": "EUR (Euro)",
        "timezone": "CET (UTC+1)",
        "power_plug": "Type C/F/L (230V)",
        "emergency_number": "112",
        "tap_water_safe": True,
        "best_transport": "Roma Pass for metro, buses, and museum discounts.",
    },
    "dubai": {
        "destination": "Dubai",
        "country": "United Arab Emirates",
        "visa_required": False,
        "visa_notes": "US citizens: visa on arrival for 30 days, free of charge.",
        "safety_level": "very_safe",
        "safety_notes": "Very safe. Strict laws — respect local customs and dress codes.",
        "currency": "AED (Dirham)",
        "timezone": "GST (UTC+4)",
        "power_plug": "Type G (230V)",
        "emergency_number": "999 (police) / 998 (ambulance)",
        "tap_water_safe": True,
        "best_transport": "Dubai Metro (Red/Green lines) and RTA buses. Nol card recommended.",
    },
    "sydney": {
        "destination": "Sydney",
        "country": "Australia",
        "visa_required": True,
        "visa_notes": "US citizens: ETA (Electronic Travel Authority) required, apply online.",
        "safety_level": "safe",
        "safety_notes": "Swim between the flags at beaches. Strong UV — wear sunscreen.",
        "currency": "AUD (Australian Dollar)",
        "timezone": "AEST (UTC+10) / AEDT (UTC+11 in summer)",
        "power_plug": "Type I (230V)",
        "emergency_number": "000",
        "tap_water_safe": True,
        "best_transport": "Opal card for trains, buses, ferries, and light rail.",
    },
    "bangkok": {
        "destination": "Bangkok",
        "country": "Thailand",
        "visa_required": False,
        "visa_notes": "US citizens: visa-free for up to 30 days (extendable to 60).",
        "safety_level": "safe",
        "safety_notes": "Watch for tuk-tuk scams. Drink bottled water. Traffic is heavy.",
        "currency": "THB (Baht)",
        "timezone": "ICT (UTC+7)",
        "power_plug": "Type A/B/C (230V)",
        "emergency_number": "191 (police) / 1669 (ambulance)",
        "tap_water_safe": False,
        "best_transport": "BTS Skytrain and MRT subway. Grab for taxis.",
    },
}

LOCAL_PHRASES: dict[str, dict] = {
    "paris": {
        "destination": "Paris", "language": "French",
        "phrases": {
            "hello": "Bonjour",
            "thank_you": "Merci",
            "please": "S'il vous plaît",
            "excuse_me": "Excusez-moi",
            "where_is": "Où est…?",
            "how_much": "Combien ça coûte?",
            "help": "Au secours!",
            "cheers": "Santé!",
        },
    },
    "tokyo": {
        "destination": "Tokyo", "language": "Japanese",
        "phrases": {
            "hello": "Konnichiwa (こんにちは)",
            "thank_you": "Arigatō gozaimasu (ありがとうございます)",
            "please": "Onegaishimasu (お願いします)",
            "excuse_me": "Sumimasen (すみません)",
            "where_is": "…wa doko desu ka? (…はどこですか?)",
            "how_much": "Ikura desu ka? (いくらですか?)",
            "help": "Tasukete! (助けて!)",
            "cheers": "Kanpai! (乾杯!)",
        },
    },
    "london": {
        "destination": "London", "language": "English",
        "phrases": {
            "hello": "Hello / Hiya",
            "thank_you": "Thank you / Cheers",
            "please": "Please",
            "excuse_me": "Excuse me / Sorry",
            "where_is": "Where is…?",
            "how_much": "How much is this?",
            "help": "Help!",
            "cheers": "Cheers!",
        },
    },
    "cancun": {
        "destination": "Cancún", "language": "Spanish",
        "phrases": {
            "hello": "Hola",
            "thank_you": "Gracias",
            "please": "Por favor",
            "excuse_me": "Disculpe",
            "where_is": "¿Dónde está…?",
            "how_much": "¿Cuánto cuesta?",
            "help": "¡Ayuda!",
            "cheers": "¡Salud!",
        },
    },
    "bali": {
        "destination": "Bali", "language": "Indonesian / Balinese",
        "phrases": {
            "hello": "Halo / Om Swastiastu (Balinese)",
            "thank_you": "Terima kasih / Suksma (Balinese)",
            "please": "Tolong",
            "excuse_me": "Permisi",
            "where_is": "Di mana…?",
            "how_much": "Berapa harganya?",
            "help": "Tolong!",
            "cheers": "Bersulang!",
        },
    },
    "new york": {
        "destination": "New York", "language": "English",
        "phrases": {
            "hello": "Hey / What's up",
            "thank_you": "Thanks",
            "please": "Please",
            "excuse_me": "Excuse me",
            "where_is": "Where's…?",
            "how_much": "How much?",
            "help": "Help!",
            "cheers": "Cheers!",
        },
    },
    "barcelona": {
        "destination": "Barcelona", "language": "Spanish / Catalan",
        "phrases": {
            "hello": "Hola / Bon dia (Catalan)",
            "thank_you": "Gracias / Gràcies (Catalan)",
            "please": "Por favor / Si us plau (Catalan)",
            "excuse_me": "Perdone / Perdoni (Catalan)",
            "where_is": "¿Dónde está…? / On és…? (Catalan)",
            "how_much": "¿Cuánto cuesta?",
            "help": "¡Ayuda! / Ajuda! (Catalan)",
            "cheers": "¡Salud! / Salut! (Catalan)",
        },
    },
    "seattle": {
        "destination": "Seattle", "language": "English",
        "phrases": {
            "hello": "Hey there",
            "thank_you": "Thanks",
            "please": "Please",
            "excuse_me": "Excuse me",
            "where_is": "Where's…?",
            "how_much": "How much is that?",
            "help": "Help!",
            "cheers": "Cheers!",
        },
    },
    "rome": {
        "destination": "Rome", "language": "Italian",
        "phrases": {
            "hello": "Ciao / Buongiorno",
            "thank_you": "Grazie",
            "please": "Per favore",
            "excuse_me": "Mi scusi",
            "where_is": "Dov'è…?",
            "how_much": "Quanto costa?",
            "help": "Aiuto!",
            "cheers": "Cin cin! / Salute!",
        },
    },
    "dubai": {
        "destination": "Dubai", "language": "Arabic / English",
        "phrases": {
            "hello": "Marhaba (مرحبا) / As-salamu alaykum",
            "thank_you": "Shukran (شكراً)",
            "please": "Min fadlak (من فضلك)",
            "excuse_me": "Afwan (عفواً)",
            "where_is": "Wayn…? (وين…؟)",
            "how_much": "Bikam? (بكم؟)",
            "help": "Musaa'da! (مساعدة!)",
            "cheers": "Fi sehetak! (في صحتك!)",
        },
    },
    "sydney": {
        "destination": "Sydney", "language": "English",
        "phrases": {
            "hello": "G'day",
            "thank_you": "Ta / Cheers",
            "please": "Please",
            "excuse_me": "Excuse me",
            "where_is": "Where's…?",
            "how_much": "How much?",
            "help": "Help!",
            "cheers": "Cheers mate!",
        },
    },
    "bangkok": {
        "destination": "Bangkok", "language": "Thai",
        "phrases": {
            "hello": "Sawadee krub/ka (สวัสดีครับ/ค่ะ)",
            "thank_you": "Khob khun krub/ka (ขอบคุณครับ/ค่ะ)",
            "please": "Ga-ru-na (กรุณา)",
            "excuse_me": "Khor thot (ขอโทษ)",
            "where_is": "…yoo tee nai? (…อยู่ที่ไหน?)",
            "how_much": "Tao rai? (เท่าไหร่?)",
            "help": "Chuay duay! (ช่วยด้วย!)",
            "cheers": "Chon gaew! (ชนแก้ว!)",
        },
    },
}


@mcp.tool()
def get_travel_advisory(destination: str) -> dict:
    """Get travel advisory information for a destination including visa requirements,
    safety level, currency, timezone, emergency numbers, and transport tips."""
    norm = destination.strip().lower()
    advisory = TRAVEL_ADVISORIES.get(norm)
    if advisory:
        return advisory
    return {
        "destination": destination,
        "country": "Unknown",
        "visa_required": True,
        "visa_notes": "Check with your country's embassy for visa requirements.",
        "safety_level": "unknown",
        "safety_notes": "Research safety conditions before traveling.",
        "currency": "Check local currency",
        "timezone": "Check local timezone",
        "power_plug": "Bring a universal adapter",
        "emergency_number": "Check local emergency number",
        "tap_water_safe": False,
        "best_transport": "Research local transport options.",
    }


@mcp.tool()
def get_local_phrases(destination: str) -> dict:
    """Get useful local phrases for a travel destination including hello,
    thank you, please, excuse me, and other essential travel phrases."""
    norm = destination.strip().lower()
    phrases = LOCAL_PHRASES.get(norm)
    if phrases:
        return phrases
    return {
        "destination": destination,
        "language": "Unknown",
        "phrases": {
            "hello": "Hello",
            "thank_you": "Thank you",
            "please": "Please",
            "excuse_me": "Excuse me",
            "where_is": "Where is…?",
            "how_much": "How much?",
            "help": "Help!",
            "cheers": "Cheers!",
        },
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
