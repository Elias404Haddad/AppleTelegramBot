from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove
import re
import sqlite3
import time
import random
from datetime import datetime
from pathlib import Path
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
import cloudscraper
from bs4 import BeautifulSoup
import os
from dotenv import load_dotenv

load_dotenv("data.env")

# ================= CONFIGURATION =================
TOKEN = os.getenv("BOT_TOKEN")
EMAIL_REGEX = re.compile(r'^([a-zA-Z0-9._%+-]+)@([a-zA-Z0-9.-]+\.com)$', re.ASCII)
DB_PATH = Path("appleid_bot.db")

# ================= IN-MEMORY STORAGE =================
ADMINS = {"@Elias_H"}
ADMIN_IDS = {int(os.getenv('MY_BOT_ID'))}
user_data_store = {}  # {chat_id: {state: data}}
admin_data_store = {}  # {admin_id: {command: state}}

# ================= DATABASE SETUP =================
def init_db():
    """Initialize the database with required tables"""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS registered_pairs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            apple_id TEXT NOT NULL UNIQUE,
            phone TEXT NOT NULL,
            added_by TEXT NOT NULL,
            added_at TEXT NOT NULL,
            last_updated TEXT
        )
        """)
        # Add new table for verified users
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS verified_users (
            chat_id INTEGER PRIMARY KEY,
            apple_id TEXT NOT NULL,
            verified_at TEXT NOT NULL,
            FOREIGN KEY(apple_id) REFERENCES registered_pairs(apple_id)
        )
        """)
        conn.commit()

# ================= DATABASE OPERATIONS =================
def add_pair(apple_id: str, phone: str, added_by: str) -> bool:
    """Add a new Apple ID-phone pair to the database"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO registered_pairs 
            (apple_id, phone, added_by, added_at)
            VALUES (?, ?, ?, ?)
            """, (apple_id, phone, added_by, datetime.now().isoformat()))
            conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False

def update_phone(apple_id: str, new_phone: str) -> bool:
    """Update phone number for existing Apple ID"""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        UPDATE registered_pairs 
        SET phone = ?, last_updated = ?
        WHERE LOWER(apple_id) = LOWER(?)
        """, (new_phone, datetime.now().isoformat(), apple_id))
        conn.commit()
    return cursor.rowcount > 0

def remove_pair(apple_id: str) -> bool:
    """Remove an Apple ID-phone pair from the database"""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        DELETE FROM registered_pairs 
        WHERE LOWER(apple_id) = LOWER(?)
        """, (apple_id,))
        conn.commit()
    return cursor.rowcount > 0

def get_all_pairs() -> list:
    """Retrieve all registered pairs"""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT apple_id, phone, added_by, added_at, last_updated 
        FROM registered_pairs
        """)
        return [{
            "apple_id": row[0],
            "phone": row[1],
            "added_by": row[2],
            "added_at": row[3],
            "last_updated": row[4]
        } for row in cursor.fetchall()]

def apple_id_exists(apple_id: str) -> bool:
    """Check if Apple ID exists in database"""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT 1 FROM registered_pairs 
        WHERE LOWER(apple_id) = LOWER(?)
        """, (apple_id,))
        return cursor.fetchone() is not None

def add_verified_user(chat_id: int, apple_id: str) -> bool:
    """Add a verified user to the database"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT OR REPLACE INTO verified_users 
            (chat_id, apple_id, verified_at)
            VALUES (?, ?, ?)
            """, (chat_id, apple_id, datetime.now().isoformat()))
            conn.commit()
        return True
    except sqlite3.Error:
        return False

def get_verified_apple_id(chat_id: int) -> str | None:
    """Get verified Apple ID for a chat if exists"""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT apple_id FROM verified_users 
        WHERE chat_id = ?
        """, (chat_id,))
        result = cursor.fetchone()
        return result[0] if result else None

def remove_verified_user(chat_id: int) -> bool:
    """Remove a verified user from the database"""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        DELETE FROM verified_users 
        WHERE chat_id = ?
        """, (chat_id,))
        conn.commit()
    return cursor.rowcount > 0

# ================= SMS SCRAPER FUNCTION =================
def get_apple_messages_content(phone_number):
    """Scrape Apple verification messages from the phone number"""
    clean_phone = re.sub(r'[^\d]', '', phone_number)
    url = f"https://receive-sms-free.cc/Free-USA-Phone-Number/{clean_phone}/"
    
    scraper = cloudscraper.create_scraper(
        delay=random.uniform(1.5, 3.5),
        browser={
            'browser': 'chrome',
            'platform': 'windows',
            'mobile': False,
            'desktop' : True
        }
    )
    
    headers = {
             'User-Agent': random.choice([
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
        ]),
        'DNT': str(random.randint(0, 1)),  # Random Do Not Track setting

        'Connection': 'keep-alive',
        'Referer': 'https://www.google.com/',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'cross-site',
        'Sec-Fetch-User': '?1'
    }
    
    try:
        # Initial request with randomized delay
        time.sleep(random.uniform(0.5, 2.5))
        
        # Make the request with timeout and retry logic
        response = scraper.get(
            url,
            headers=headers,
            timeout=(random.uniform(5, 8), random.uniform(10, 15))
        )
        response.raise_for_status()

        # Random delay before parsing
        time.sleep(random.uniform(0.3, 1.2))

        soup = BeautifulSoup(response.text, 'lxml')
        apple_contents = []
        messages_checked = 0
        
        for row in soup.find_all('div', class_=lambda x: x and ('row border-bottom table-hover' in x or 'bg-messages' in x)):
            if messages_checked >= 3:
                break
                
            if 'adsbygoogle' in str(row):
                continue
                
            sender = row.find(['div', 'a'], class_=lambda x: x and ('col-xs-12 col-md-2' in x or 'mobile_show message_head' in x))
            content = row.find('div', class_='col-xs-12 col-md-8')
            
            if sender and content:
                messages_checked += 1
                if 'Apple' in sender.get_text(strip=True):
                    apple_contents.append(content.get_text(strip=True))

        return apple_contents
        
    except Exception as e:
        print(f"Error: {e}")
        return []

# ================= HELPER FUNCTIONS =================
def is_admin(user) -> bool:
    """Check if user is admin by username or ID"""
    if not user:
        return False
    username = getattr(user, 'username', '').lower()
    return (username in {a.lower() for a in ADMINS}) or (user.id in ADMIN_IDS)

async def show_user_commands(update: Update, context: ContextTypes.DEFAULT_TYPE = None):
    """Show available commands to regular users"""
    await update.message.reply_text("🛠 Available Command:\n/get_verification - Get verification")

async def show_admin_commands(update: Update, context: ContextTypes.DEFAULT_TYPE = None):
    """Show available commands to admins"""
    await update.message.reply_text(
        "🛠 Available Commands:\n"
        "/get_verification - Get verification\n\n"
        "🔧 Admin Commands:\n"
        "/appleID_admin - Apple ID management"
    )

# ================= USER FLOW =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Enhanced start command with registration options"""
    chat_id = update.effective_chat.id
    
    if is_admin(update.effective_user):
        await show_admin_commands(update)
        return
    
    # Always clear previous state
    user_data_store[chat_id] = {}
    
    existing_apple_id = get_verified_apple_id(chat_id)
    if existing_apple_id:
        # Store both state and existing ID
        user_data_store[chat_id] = {
            "state": "choose_option",
            "existing_apple_id": existing_apple_id
        }
        
        reply_markup = ReplyKeyboardMarkup(
            [["Use existing Apple ID", "Enter new Apple ID"]],
            one_time_keyboard=True,
            resize_keyboard=True
        )
        
        await update.message.reply_text(
            f"We found your registered Apple ID: {existing_apple_id}\n"
            "Would you like to continue with this ID or enter a new one?",
            reply_markup=reply_markup
        )
    else:
        user_data_store[chat_id] = {"state": "awaiting_apple_id"}
        await update.message.reply_text(
            "Please enter your Apple ID (format: name@domain.com):",
            reply_markup=ReplyKeyboardRemove()
        )

async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_data = user_data_store.get(chat_id, {})
    text = update.message.text.strip()

    if user_data.get("state") == "choose_option":
        if text == "Use existing Apple ID":
            apple_id = user_data["existing_apple_id"]
            if apple_id_exists(apple_id):
                user_data_store[chat_id] = {
                    "verified": True,
                    "apple_id": apple_id
                }
                await update.message.reply_text(
                    f"✅ Using your existing Apple ID: {apple_id}",
                    reply_markup=ReplyKeyboardRemove()
                )
                await show_user_commands(update)
            else:
                await update.message.reply_text(
                    "❌ This Apple ID is no longer valid. Please enter a new one:",
                    reply_markup=ReplyKeyboardRemove()
                )
                user_data_store[chat_id] = {"state": "awaiting_apple_id"}
        
        elif text == "Enter new Apple ID":
            await update.message.reply_text(
                "Please enter your new Apple ID:",
                reply_markup=ReplyKeyboardRemove()
            )
            user_data_store[chat_id] = {"state": "awaiting_apple_id"}
        
        return

    if user_data.get("state") == "awaiting_apple_id":
        if not EMAIL_REGEX.fullmatch(text):
            await update.message.reply_text("❌ Invalid format! Please enter a valid Apple ID:")
            return
            
        if apple_id_exists(text):
            add_verified_user(chat_id, text)
            user_data_store[chat_id] = {
                "verified": True,
                "apple_id": text
            }
            await update.message.reply_text("✅ Apple ID verified!")
            await show_user_commands(update)
        else:
            await update.message.reply_text("❌ Apple ID not found. Please try again:")

async def get_verification(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Verification process for users with SMS scraping"""
    chat_id = update.effective_chat.id
    
    # Check memory first, then database
    if not user_data_store.get(chat_id, {}).get("verified"):
        apple_id = get_verified_apple_id(chat_id)
        if apple_id:
            user_data_store[chat_id] = {
                "verified": True,
                "apple_id": apple_id
            }
        else:
            await update.message.reply_text("⚠️ Please verify your Apple ID first by sending it to me.")
            return
    
    # Get the user's Apple ID from storage
    apple_id = user_data_store[chat_id].get("apple_id")
    if not apple_id:
        await update.message.reply_text("❌ Your Apple ID couldn't be found. Please register again.")
        return
    
    # Get the associated phone number from database
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT phone FROM registered_pairs 
        WHERE LOWER(apple_id) = LOWER(?)
        """, (apple_id,))
        result = cursor.fetchone()
        if not result:
            await update.message.reply_text("❌ No phone number found for your Apple ID.")
            return
        
        phone_number = result[0]
    
    await update.message.reply_text("🔍 Searching for Apple verification messages...")
    
    # Implement the scraping logic with retries
    max_retries = 2
    retry_count = 0
    apple_messages = []
    
    while retry_count <= max_retries:
        try:
            apple_messages = get_apple_messages_content(phone_number)
            
            if apple_messages:
                break
            else:
                if retry_count < max_retries:
                    wait_time = random.uniform(5, 15)
                    await update.message.reply_text(
                        f"⏳ No messages found yet (attempt {retry_count + 1}/{max_retries + 1})\n"
                        f"Waiting {wait_time:.1f} seconds before retry..."
                    )
                    time.sleep(wait_time)
                retry_count += 1
        except Exception as e:
            await update.message.reply_text(f"⚠️ Error during search: {str(e)}")
            break
    
    if apple_messages:
        message = "✅ Found Apple verification messages:\n\n"
        for idx, content in enumerate(apple_messages, 1):
            message += f"{idx}. {content}\n\n"
        await update.message.reply_text(message)
    else:
        await update.message.reply_text("❌ No Apple verification messages found after all attempts.")
    
    await show_user_commands(update)

# ================= ADMIN COMMANDS =================
async def appleID_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Apple ID management panel"""
    if not is_admin(update.effective_user):
        await update.message.reply_text("⛔ Admin access required")
        return

    message = "🍎 Apple ID Admin:\n\n"
    message += "🔧 /register_pair - Register Apple ID + phone\n"
    message += "🔄 /replace_phone - Update phone number\n"
    message += "🗑 /remove_pair - Remove a pair\n"
    message += "📋 /list_pairs - View all pairs\n"
    message += "🔙 /back - Main menu"
    await update.message.reply_text(message)

async def register_pair(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to register new account"""
    if not is_admin(update.effective_user):
        await update.message.reply_text("⛔ Admin access required")
        return

    admin_data_store[update.effective_user.id] = {
        "command": "register_pair", 
        "step": 1  # Step 1: Apple ID
    }
    await update.message.reply_text(
        "Please enter the Apple ID to register (format: user@domain.com):\n"
        "Example: john.doe@icloud.com"
    )

async def replace_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Replace phone number for existing Apple ID"""
    if not is_admin(update.effective_user):
        await update.message.reply_text("⛔ Admin access required")
        return

    admin_data_store[update.effective_user.id] = {
        "command": "replace_phone", 
        "step": 1  # Step 1: Waiting for Apple ID
    }
    await update.message.reply_text("Enter the REGISTERED Apple ID to update its phone number:")

async def remove_pair_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to remove existing account"""
    if not is_admin(update.effective_user):
        await update.message.reply_text("⛔ Admin access required")
        return

    admin_data_store[update.effective_user.id] = {
        "command": "remove_pair", 
        "step": 1  # Step 1: Waiting for Apple ID
    }
    await update.message.reply_text("Enter the Apple ID to remove:")

async def list_pairs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all registered accounts"""
    if not is_admin(update.effective_user):
        await update.message.reply_text("⛔ Admin access required")
        return

    pairs = get_all_pairs()
    if not pairs:
        await update.message.reply_text("ℹ️ No accounts registered yet")
    else:
        message = "📋 Registered Accounts:\n\n"
        for idx, acc in enumerate(pairs, 1):
            message += f"{idx}. 🆔 Apple ID: {acc.get('apple_id', 'N/A')}\n"
            message += f"   📞 Phone: {acc.get('phone', 'N/A')}\n"
            message += f"   👤 Added by: {acc.get('added_by', 'N/A')}\n"
            message += f"   🕒 Added: {acc.get('added_at', 'N/A')}\n"
            if acc.get('last_updated'):
                message += f"   🔄 Updated: {acc['last_updated']}\n"
            message += "\n"
        
        await update.message.reply_text(message)
    await appleID_admin(update, context)

async def back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return to main menu"""
    if is_admin(update.effective_user):
        await show_admin_commands(update)
    else:
        await show_user_commands(update)

async def handle_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    command_data = admin_data_store.get(user_id, {})
    command = command_data.get("command")
    user_input = update.message.text.strip()

    try:
        if command == "register_pair":
            if command_data.get("step") == 1:
                # Validate Apple ID format first
                if not EMAIL_REGEX.fullmatch(user_input):
                    await update.message.reply_text(
                        "❌ Invalid Apple ID format!\n"
                        "Must be a valid email (user@domain.com)\n"
                        "Please try again:"
                    )
                    return  # Stay in same step until valid input
                
                # Check if Apple ID already exists
                if apple_id_exists(user_input):
                    await update.message.reply_text(
                        "❌ This Apple ID is already registered!\n"
                        "Please enter a different Apple ID:"
                    )
                    return

                admin_data_store[user_id] = {
                    "command": "register_pair",
                    "step": 2,
                    "apple_id": user_input
                }
                await update.message.reply_text(
                    "✅ Valid Apple ID!\n"
                    "Now please enter the PHONE NUMBER (format: +1234567890):\n"
                    "Example: +15551234567"
                )
                return
            
            elif command_data.get("step") == 2:
                # Basic phone number validation
                if not user_input.startswith('+'):
                    await update.message.reply_text(
                        "❌ Phone number must start with '+' country code!\n"
                        "Please try again:"
                    )
                    return

                if len(user_input) < 10:
                    await update.message.reply_text(
                        "❌ Phone number too short!\n"
                        "Please include country code and area code\n"
                        "Example: +15551234567\n"
                        "Please try again:"
                    )
                    return

                success = add_pair(
                    apple_id=command_data["apple_id"],
                    phone=user_input,
                    added_by=update.effective_user.username or str(user_id)
                )

                if not success:
                    await update.message.reply_text("❌ Unexpected error saving to database")
                else:
                    await update.message.reply_text(
                        f"✅ Successfully registered:\n"
                        f"Apple ID: {command_data['apple_id']}\n"
                        f"Phone: {user_input}"
                    )
                
                admin_data_store.pop(user_id, None)
                await appleID_admin(update, context)
                return

        elif command == "replace_phone":
            if command_data.get("step") == 1:
                if not apple_id_exists(user_input):
                    raise ValueError("Apple ID not found in registered pairs")
                
                admin_data_store[user_id] = {
                    "command": "replace_phone",
                    "step": 2,
                    "apple_id": user_input
                }
                await update.message.reply_text("Enter the NEW PHONE NUMBER:")
                return
            
            elif command_data.get("step") == 2:
                success = update_phone(
                    apple_id=command_data["apple_id"],
                    new_phone=user_input
                )

                if not success:
                    await update.message.reply_text("❌ Failed to update phone number")
                    return

                await update.message.reply_text(
                    f"✅ Successfully updated phone number:\n"
                    f"Apple ID: {command_data['apple_id']}\n"
                    f"New phone: {user_input}"
                )
                admin_data_store.pop(user_id, None)
                await appleID_admin(update, context)
                return

        elif command == "remove_pair":
            if command_data.get("step") == 1:
                if not apple_id_exists(user_input):
                    raise ValueError("Apple ID not found in registered pairs")
                
                success = remove_pair(user_input)
                
                if not success:
                    await update.message.reply_text("❌ Failed to remove the pair")
                else:
                    await update.message.reply_text(
                        f"✅ Successfully removed:\n"
                        f"Apple ID: {user_input}"
                    )
                
                admin_data_store.pop(user_id, None)
                await appleID_admin(update, context)
                return

    except ValueError as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
        if command in ["register_pair", "replace_phone", "remove_pair"]:
            await appleID_admin(update, context)
    except Exception as e:
        await update.message.reply_text(f"❌ Operation failed: {str(e)}")
        admin_data_store.pop(user_id, None)
        await appleID_admin(update, context)

async def handle_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle all incoming messages and route them appropriately"""
    user_id = update.effective_user.id
    
    # Check if this is an admin in the middle of a command
    if user_id in admin_data_store:
        await handle_admin_input(update, context)
    # Check if this is a regular user in verification flow
    elif update.effective_chat.id in user_data_store:
        await handle_user_message(update, context)
    else:
        # If none of the above, show appropriate commands
        if is_admin(update.effective_user):
            await show_admin_commands(update)
        else:
            await show_user_commands(update)

# ================= MAIN APPLICATION =================
def main() -> None:
    # Initialize database
    init_db()
    
    app = Application.builder().token(TOKEN).build()
    
    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("get_verification", get_verification))
    app.add_handler(CommandHandler("back", back))
    app.add_handler(CommandHandler("appleID_admin", appleID_admin))
    app.add_handler(CommandHandler("register_pair", register_pair))
    app.add_handler(CommandHandler("replace_phone", replace_phone))
    app.add_handler(CommandHandler("remove_pair", remove_pair_command))
    app.add_handler(CommandHandler("list_pairs", list_pairs))
    
    # Message handler - now using a single handler for all messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_all_messages))
    
    app.run_polling()

if __name__ == "__main__":
    main()