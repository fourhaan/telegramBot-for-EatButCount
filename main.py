import logging
import os
import re
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from agent import run_agent

# --------------------------
# Logging
# --------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

logger = logging.getLogger(__name__)

# --------------------------
# Load environment variables
# --------------------------
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(env_path)

TOKEN = os.getenv("TELEGRAM_TOKEN")
SUPABASE_URL = os.getenv("VITE_SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

supabase_auth = create_client(SUPABASE_URL, SUPABASE_KEY)
supabase_admin = create_client(
    SUPABASE_URL,
    SUPABASE_KEY,
)

# --------------------------
# Check if MCP server is running
# --------------------------
async def check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        result = await run_agent(intent="health")
        if result.get("result"):
            await update.message.reply_text(
                "✅ Bot running\n✅ MCP health tool reachable"
            )
        else:
            await update.message.reply_text(
                "⚠️ MCP health tool returned empty response"
            )

    except Exception as e:
        logger.exception("MCP check failed")
        await update.message.reply_text(
            "❌ MCP server/tools not reachable"
        )


# --------------------------
# Food logging command
# --------------------------
async def food(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.args:
        await update.message.reply_text(
            "Usage:\n/food 2 eggs and a banana"
        )
        return

    food_text = " ".join(context.args)
    telegram_id = update.effective_user.id

    try:
        result = await run_agent(
            intent="food",
            message=food_text,
            telegram_id=telegram_id,
        )
        macros = result.get("macros", {})

        await update.message.reply_text(
            "✅ Food logged\n"
            f"Food: {macros.get('food', '-') }\n"
            f"Calories: {macros.get('calories', 0)}\n"
            f"Protein: {macros.get('protein', 0)}g\n"
            f"Carbs: {macros.get('carbs', 0)}g\n"
            f"Fat: {macros.get('fat', 0)}g"
        )

    except Exception as e:
        logger.exception("Food processing failed")
        await update.message.reply_text(
            "❌ Error processing food"
        )


# --------------------------
# Register telegram link command
# --------------------------
async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage:\n/register your_email your_password"
        )
        return

    email = context.args[0].strip()
    password = " ".join(context.args[1:]).strip()
    telegram_id = update.effective_user.id

    try:
        auth_result = supabase_auth.auth.sign_in_with_password(
            {"email": email, "password": password}
        )
        user = auth_result.user
        if not user:
            await update.message.reply_text(
                "❌ Login failed. Check email and password."
            )
            return

        supabase_admin.table("telegram_links").upsert(
            {
                "telegram_id": telegram_id,
                "uid": user.id,
            },
            on_conflict="telegram_id",
        ).execute()

        await update.message.reply_text("✅ Telegram linked to your account")
    except Exception:
        logger.exception("Register command failed")
        await update.message.reply_text(
            "❌ Could not link account. Verify credentials and DB policy."
        )


# --------------------------
# Query command
# --------------------------
async def query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query_text = " ".join(context.args).strip() or "what all i ate today"
    telegram_id = update.effective_user.id

    try:
        result = await run_agent(
            intent="query",
            message=query_text,
            telegram_id=telegram_id,
        )

        logs = result.get("logs", [])
        totals = result.get("totals", {})

        if not logs:
            await update.message.reply_text("No food logs found for today.")
            return

        q = query_text.lower()
        last_n = None
        match = re.search(r"(?:last|recent)\s+(\d+)", q)
        if match:
            last_n = max(1, int(match.group(1)))

        macro_requested = []
        if "calorie" in q:
            macro_requested.append("calories")
        if "protein" in q:
            macro_requested.append("protein")
        if "carb" in q:
            macro_requested.append("carbs")
        if "fat" in q:
            macro_requested.append("fat")

        ask_count = any(phrase in q for phrase in ["how many", "count", "entries"])
        ask_list = any(
            phrase in q
            for phrase in ["what all", "what did i eat", "i ate", "list", "show", "foods", "meals"]
        )
        ask_total = any(phrase in q for phrase in ["total", "sum", "overall", "consumed"]) or bool(macro_requested)

        selected_logs = logs[:last_n] if last_n else logs
        lines = []

        if ask_count:
            if last_n:
                lines.append(f"Entries in the last {last_n}: {len(selected_logs)}")
            else:
                lines.append(f"Today's total entries: {len(logs)}")

        if ask_list or not (ask_count or ask_total):
            list_title = f"Last {last_n} entries:" if last_n else "Today's entries:"
            lines.append(list_title)
            for idx, item in enumerate(selected_logs, start=1):
                lines.append(
                    f"{idx}. {item.get('food', 'Unknown')} - "
                    f"C:{item.get('calories', 0)} "
                    f"P:{item.get('protein', 0)}g "
                    f"Cb:{item.get('carbs', 0)}g "
                    f"F:{item.get('fat', 0)}g"
                )

        if ask_total:
            lines.append("")
            lines.append("Totals:")
            if macro_requested:
                for macro in macro_requested:
                    label = macro.capitalize()
                    suffix = "g" if macro != "calories" else ""
                    lines.append(f"{label}: {totals.get(macro, 0)}{suffix}")
            else:
                lines.append(f"Calories: {totals.get('calories', 0)}")
                lines.append(f"Protein: {totals.get('protein', 0)}g")
                lines.append(f"Carbs: {totals.get('carbs', 0)}g")
                lines.append(f"Fat: {totals.get('fat', 0)}g")

        await update.message.reply_text("\n".join(lines).strip())
    except Exception:
        logger.exception("Query command failed")
        await update.message.reply_text(
            "❌ Could not fetch logs. Try /register first if not linked."
        )


# --------------------------
# Help command
# --------------------------
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Available commands:\n\n"
        "/help\n"
        "Show all commands with examples.\n"
        "Example: /help\n\n"
        "/check\n"
        "Check bot and MCP connectivity.\n"
        "Example: /check\n\n"
        "/register <email> <password>\n"
        "Link your Telegram account with your app account.\n"
        "Example: /register you@example.com MyStrongPass123\n\n"
        "/food <what you ate>\n"
        "Log a food entry with estimated macros.\n"
        "Example: /food 2 eggs and a banana\n\n"
        "/query [question]\n"
        "Query today's food logs dynamically.\n"
        "Examples:\n"
        "/query what all i ate today\n"
        "/query total calories today\n"
        "/query total protein and carbs\n"
        "/query how many entries today\n"
        "/query show last 2 entries"
    )


# --------------------------
# Main
# --------------------------
def main():

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("check", check))
    app.add_handler(CommandHandler("food", food))
    app.add_handler(CommandHandler("register", register))
    app.add_handler(CommandHandler("query", query))
    app.add_handler(CommandHandler("help", help_command))

    print("🤖 Telegram Bot started")

    app.run_polling()


if __name__ == "__main__":
    main()