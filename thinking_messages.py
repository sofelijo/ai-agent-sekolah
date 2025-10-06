import random

THINKING_MESSAGES = [
    # --- VIBE CEPAT & SAT SET ---
    "ASKA lagi gercep, sat set, no yapping! 🏃‍♀️💨🧠",
    "Wusshh! ASKA lagi cari info kilat, tungguin! ⚡️🧐",
    "ASKA OTW proses, no cap cepet! 🚀💯",

    # --- SLANG KEKINIAN & RELATABLE ---
    "Sabar ya bestie, lagi *let ASKA cook*! 🔥👩‍🍳🧠",
    "Bentar, ASKA lagi *brain rot* dulu buat cari ide... 🌀🧠💭",
    "Tungguin, ASKA lagi mau spill the tea... 🍵👀",
    "Tunggu hasilnya dijamin slay~ ASKA proses dulu! 💅✨",

    # --- VIBE CERDAS & KOCAK (THE BEST FROM BEFORE) ---
    "Bentar, otak ASKA lagi loading... ⏳🤖",
    "ASKA lagi overthinking dulu, xixixi 😵‍💫😂",
    "Big brain time! ASKA lagi analisis nih... 🧠📊",
    "ASKA lagi stalking datanya dulu ya... 🕵️‍♀️📂",
    "Lagi di-magic-in sama ASKA nih... ✨🔮",
    "ASKA lagi validating data... biar gak salah info, yagesya ✅🧠",
    "ASKA lagi connecting the dots... sabar yaa 🔗🤓",
    "Oke, ASKA proses dulu, jangan di-ghosting ya! 👻📞"
]


def get_random_thinking_message() -> str:
    return random.choice(THINKING_MESSAGES)
