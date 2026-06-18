import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    GUILD_ID = int(os.getenv("GUILD_ID", "0"))