import asyncio
import json
import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Message,
)


#  НАСТРОЙКА БОТА

BOT_TOKEN = os.getenv(
    "BOT_TOKEN",
    "8966498318:AAGmD0DRwsKoruxZdo9aySidmbt0ZmbPGVQ",  
)

DATA_FILE = Path("habits_data.json")
WEEKDAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()



#  ХРАНИЛИЩЕ ДАННЫХ

user_data: Dict[str, Dict] = {}


def load_data() -> None:
    global user_data
    if DATA_FILE.exists():
        try:
            user_data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            logging.info("Загружено пользователей: %d", len(user_data))
        except Exception as e:
            logging.error("Не удалось прочитать %s: %s", DATA_FILE, e)
            user_data = {}
    else:
        user_data = {}


def save_data() -> None:
    try:
        DATA_FILE.write_text(
            json.dumps(user_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logging.error("Не удалось сохранить %s: %s", DATA_FILE, e)


def get_user(user_id: int) -> Dict:
    key = str(user_id)
    if key not in user_data:
        user_data[key] = {"habits": []}
    return user_data[key]


def get_habits(user_id: int) -> List[Dict]:
    return get_user(user_id)["habits"]


def sorted_habits(user_id: int) -> List[Dict]:
    return sorted(get_habits(user_id), key=lambda h: h.get("time") or "99:99")


#  FSM

class HabitFSM(StatesGroup):
    waiting_name = State()
    waiting_time = State()


#  УТИЛИТЫ

def is_valid_time(s: str) -> bool:
    try:
        datetime.strptime(s, "%H:%M")
        return True
    except ValueError:
        return False


def today_iso() -> str:
    return date.today().isoformat()


def is_done_today(habit: Dict) -> bool:
    return today_iso() in habit["done_dates"]


def calc_streak(done: List[str]) -> int:
    if not done:
        return 0
    done_set = set(done)
    today = date.today()
    if today.isoformat() in done_set:
        cursor = today
    elif (today - timedelta(days=1)).isoformat() in done_set:
        cursor = today - timedelta(days=1)
    else:
        return 0
    streak = 0
    while cursor.isoformat() in done_set:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def calc_best_streak(done: List[str]) -> int:
    if not done:
        return 0
    days = sorted({date.fromisoformat(d) for d in done})
    best = cur = 1
    for i in range(1, len(days)):
        cur = cur + 1 if (days[i] - days[i - 1]).days == 1 else 1
        best = max(best, cur)
    return best


def calc_done_last_n(done: List[str], n: int) -> int:
    threshold = (date.today() - timedelta(days=n - 1)).isoformat()
    return sum(1 for d in done if d >= threshold)


#  КЛАВИАТУРА

def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ Привычка", callback_data="add_habit"),
                InlineKeyboardButton(text="☑️ Чек-лист", callback_data="list"),
            ],
            [
                InlineKeyboardButton(text="📊 Статистика", callback_data="stats"),
                InlineKeyboardButton(text="🗓 Карта", callback_data="map"),
            ],
            [
                InlineKeyboardButton(text="🌙 Итоги дня", callback_data="sleep"),
            ],
        ]
    )


def checklist_keyboard(user_id: int) -> Optional[InlineKeyboardMarkup]:
    
    habits = sorted_habits(user_id)
    if not habits:
        return None

    rows: List[List[InlineKeyboardButton]] = []
    for i, h in enumerate(habits):
        checked = is_done_today(h)
        box = "☑️" if checked else "☐"
        t = h.get("time") or "--:--"
        text = f"{box} {t}  {h['name'][:25]}"
        rows.append([
            InlineKeyboardButton(text=text, callback_data=f"toggle:{i}"),
            InlineKeyboardButton(text="🗑", callback_data=f"del:{i}"),
        ])

    rows.append([
        InlineKeyboardButton(text="🔄 Обновить", callback_data="list_refresh"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)



def checklist_header(user_id: int) -> str:
    habits = get_habits(user_id)
    if not habits:
        return (
            "📭 Список пуст.\n"
            "Добавь первую привычку командой /habits."
        )

    done = sum(1 for h in habits if is_done_today(h))
    total = len(habits)
    percent = round(done / total * 100) if total else 0

    return (
        f"☑️ <b>Чек-лист на {today_iso()}</b>\n"
        f"Выполнено: {done} из {total} ({percent}%)\n\n"
        f"Нажмите на привычку, чтобы отметить её.\n"
        f"🗑 — удалить."
    )


def today_stats_text(user_id: int) -> str:
    habits = get_habits(user_id)
    if not habits:
        return "Привычек пока нет. Добавь их командой /habits."

    done = [h["name"] for h in habits if is_done_today(h)]
    not_done = [h["name"] for h in habits if not is_done_today(h)]
    total = len(habits)
    percent = round(len(done) / total * 100) if total else 0

    lines = [
        f"📅 Дата: {today_iso()}",
        f"✅ Выполнено: {len(done)} из {total} ({percent}%)",
    ]
    if done:
        lines.append("\nВыполненные:")
        lines += [f"  ✅ {n}" for n in done]
    if not_done:
        lines.append("\nНе выполненные:")
        lines += [f"  ❌ {n}" for n in not_done]
    return "\n".join(lines)


def stats_text(user_id: int) -> str:
    habits = sorted_habits(user_id)
    if not habits:
        return "📭 Пока нет привычек.\nДобавьте их командой /habits."

    lines = ["📊 СТАТИСТИКА ПРИВЫЧЕК", "━" * 30]
    total_all = total_week = total_month = 0

    for h in habits:
        done = h["done_dates"]
        streak = calc_streak(done)
        best = calc_best_streak(done)
        week = calc_done_last_n(done, 7)
        month = calc_done_last_n(done, 30)
        total_all += len(done)
        total_week += week
        total_month += month

        mark = "✅" if is_done_today(h) else "⬜"
        t = h.get("time") or "--:--"
        lines.append(f"\n{mark} {t}  {h['name']}")
        lines.append(f"   🔥 Серия: {streak} дн.  (рекорд: {best})")
        lines.append(f"   📅 За 7 дней: {week}/7   За 30 дней: {month}/30")
        lines.append(f"   🧮 Всего: {len(done)}")

    lines += [
        "",
        "━" * 30,
        f"📦 Привычек: {len(habits)}",
        f"🧮 Всего отметок: {total_all}",
        f"📅 За неделю: {total_week}",
        f"📆 За месяц: {total_month}",
    ]
    max_week = len(habits) * 7
    if max_week:
        lines.append(f"🎯 Прогресс недели: {round(total_week / max_week * 100)}%")
    return "\n".join(lines)


def map_text(user_id: int) -> str:
    habits = sorted_habits(user_id)
    if not habits:
        return "📭 Пока нет привычек. Добавь их командой /habits."

    today = date.today()
    start = today - timedelta(days=today.weekday())
    week_days = [start + timedelta(days=i) for i in range(7)]

    lines = ["🗓 КАРТА НА НЕДЕЛЮ", "━" * 28]
    header = "Привычка".ljust(18)
    for d in week_days:
        header += WEEKDAYS_RU[d.weekday()] + " "
    lines += [header, "─" * 28]

    for h in habits:
        t = h.get("time")
        label = f"{t} {h['name'][:9]}" if t else h["name"][:14]
        row = label.ljust(18)
        for d in week_days:
            iso = d.isoformat()
            if iso in h["done_dates"]:
                row += "✅ "
            elif d < today:
                row += "❌ "
            elif d == today:
                row += "⏳ "
            else:
                row += "⬜ "
        lines.append(row)

    lines += [
        "─" * 28,
        "Легенда: ✅ · ❌ · ⏳ · ⬜",
        f"Неделя: {week_days[0]:%d.%m} — {week_days[-1]:%d.%m.%Y}",
    ]
    return "\n".join(lines)


#  КОМАНДЫ

@dp.message(Command("start"))
async def cmd_start(message: Message):
    name = message.from_user.first_name or "друг"
    await message.answer(
        f"Добрый день, {name}! 👋\n"
        f"Я — трекер привычек 💪\n"
        f"Добавляй привычки и отмечай их каждый день.\n\n"
        f"Меню — /help",
        reply_markup=main_menu(),
    )


@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "Как пользоваться:\n"
        "1. /habits — добавь новую привычку.\n"
        "2. /list   — чек-лист: отмечай ☐ → ☑️ прямо здесь.\n"
        "3. /stats  — серия и всего выполнений.\n"
        "4. /map    — карта привычек на неделю.\n"
        "5. /sleep  — итоги дня.\n"
        "6. /del    — удалить привычку.",
        reply_markup=main_menu(),
    )


@dp.message(Command("sleep"))
async def cmd_sleep(message: Message):
    await message.answer(
        "Планы на сегодня завершены, статистика по сегодняшнему дню:\n\n"
        f"{today_stats_text(message.from_user.id)}"
    )


@dp.message(Command("map"))
async def cmd_map(message: Message):
    await message.answer(f"<pre>{map_text(message.from_user.id)}</pre>", parse_mode="HTML")


@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    await message.answer(stats_text(message.from_user.id))


@dp.message(Command("list"))
async def cmd_list(message: Message):
    kb = checklist_keyboard(message.from_user.id)
    if kb is None:
        await message.answer(
            "📭 У вас пока нет привычек.\nДобавьте их командой /habits."
        )
        return
    await message.answer(
        checklist_header(message.from_user.id),
        reply_markup=kb,
        parse_mode="HTML",
    )


@dp.message(Command("check"))
async def cmd_check_alias(message: Message):
    await cmd_list(message)


# ================= /habits =================

@dp.message(Command("habits"))
async def cmd_habits(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "➕ Добавим новую привычку.\n\n"
        "Шаг 1 из 2. Введите название привычки\n"
        "(например: «Зарядка», «Чтение 20 минут»).\n\n"
        "Для отмены — /cancel."
    )
    await state.set_state(HabitFSM.waiting_name)


@dp.message(HabitFSM.waiting_name)
async def process_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if not name:
        await message.answer("⚠️ Название не должно быть пустым:")
        return
    if len(name) > 50:
        await message.answer("⚠️ Максимум 50 символов:")
        return

    existing = {h["name"].lower() for h in get_habits(message.from_user.id)}
    if name.lower() in existing:
        await message.answer(f"⚠️ Привычка «{name}» уже есть. Введите другое название или /cancel.")
        return

    await state.update_data(name=name)
    await message.answer(
        f"Шаг 2 из 2. Во сколько напоминать о привычке «{name}»?\n\n"
        f"Формат ЧЧ:ММ (например, 07:30).\n"
        f"Без времени — /skip.  Отмена — /cancel."
    )
    await state.set_state(HabitFSM.waiting_time)


async def _finish_add(message: Message, state: FSMContext, t: Optional[str]) -> None:
    data = await state.get_data()
    name = data.get("name")
    get_habits(message.from_user.id).append(
        {"name": name, "time": t, "done_dates": []}
    )
    save_data()
    await state.clear()
    t_info = f"на {t}" if t else "без времени"
    await message.answer(
        f"✅ Привычка «{name}» добавлена {t_info}.\n\n"
        f"/list — открыть чек-лист   /map — карта"
    )


@dp.message(HabitFSM.waiting_time, Command("skip"))
async def process_skip(message: Message, state: FSMContext):
    await _finish_add(message, state, None)


@dp.message(HabitFSM.waiting_time, Command("cancel"))
async def process_cancel_in_time(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Добавление отменено.")


@dp.message(HabitFSM.waiting_time)
async def process_time(message: Message, state: FSMContext):
    t = (message.text or "").strip()
    if not is_valid_time(t):
        await message.answer(
            "⚠️ Неверный формат. Введите ЧЧ:ММ, либо /skip, либо /cancel."
        )
        return
    await _finish_add(message, state, t)


# ================= /del =================

@dp.message(Command("del"))
async def cmd_del(message: Message):
    habits = sorted_habits(message.from_user.id)
    if not habits:
        await message.answer("📭 Нечего удалять.")
        return

    rows: List[List[InlineKeyboardButton]] = []
    for i, h in enumerate(habits):
        t = h.get("time") or "--:--"
        rows.append([
            InlineKeyboardButton(
                text=f"🗑 {t}  {h['name'][:25]}",
                callback_data=f"del:{i}",
            )
        ])
    await message.answer(
        "Выберите привычку для удаления:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    if await state.get_state() is None:
        await message.answer("Нечего отменять.")
        return
    await state.clear()
    await message.answer("❌ Действие отменено.")



#  CALLBACK-ОБРАБОТЧИКИ

@dp.callback_query(F.data.startswith("toggle:"))
async def cb_toggle(call: CallbackQuery):
    idx = int(call.data.split(":", 1)[1])
    habits = sorted_habits(call.from_user.id)
    if not (0 <= idx < len(habits)):
        await call.answer("⚠️ Привычка не найдена", show_alert=False)
        return

    habit = habits[idx]
    today = today_iso()
    if today in habit["done_dates"]:
        habit["done_dates"].remove(today)
        status = "снята галочка"
    else:
        habit["done_dates"].append(today)
        status = "отмечено"

    save_data()
    await call.answer(f"{'☑️' if is_done_today(habit) else '☐'} «{habit['name']}» — {status}")

    try:
        await call.message.edit_text(
            checklist_header(call.from_user.id),
            reply_markup=checklist_keyboard(call.from_user.id),
            parse_mode="HTML",
        )
    except Exception:
        pass


@dp.callback_query(F.data.startswith("del:"))
async def cb_del(call: CallbackQuery):
    idx = int(call.data.split(":", 1)[1])
    habits = sorted_habits(call.from_user.id)
    if not (0 <= idx < len(habits)):
        await call.answer("⚠️ Привычка не найдена", show_alert=False)
        return

    removed = habits[idx]
    get_habits(call.from_user.id).remove(removed)
    save_data()
    await call.answer(f"🗑 «{removed['name']}» удалена")

    kb = checklist_keyboard(call.from_user.id)
    try:
        if kb is None:
            await call.message.edit_text(
                "📭 Список привычек пуст.\nДобавьте новую командой /habits."
            )
        else:
            # Если это список удаления (/del) — перерисуем его
            if call.message.text and "удаления" in (call.message.text or ""):
                rows: List[List[InlineKeyboardButton]] = []
                for i, h in enumerate(sorted_habits(call.from_user.id)):
                    t = h.get("time") or "--:--"
                    rows.append([
                        InlineKeyboardButton(
                            text=f"🗑 {t}  {h['name'][:25]}",
                            callback_data=f"del:{i}",
                        )
                    ])
                await call.message.edit_reply_markup(
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
                )
            else:
                await call.message.edit_text(
                    checklist_header(call.from_user.id),
                    reply_markup=kb,
                    parse_mode="HTML",
                )
    except Exception:
        pass


@dp.callback_query(F.data == "list_refresh")
async def cb_list_refresh(call: CallbackQuery):
    kb = checklist_keyboard(call.from_user.id)
    try:
        if kb is None:
            await call.message.edit_text("📭 Список пуст.")
        else:
            await call.message.edit_text(
                checklist_header(call.from_user.id),
                reply_markup=kb,
                parse_mode="HTML",
            )
    except Exception:
        pass
    await call.answer("Обновлено")


@dp.callback_query(F.data == "stats")
async def cb_stats(call: CallbackQuery):
    await call.answer()
    await call.message.answer(stats_text(call.from_user.id))


@dp.callback_query(F.data == "list")
async def cb_list(call: CallbackQuery):
    await call.answer()
    kb = checklist_keyboard(call.from_user.id)
    if kb is None:
        await call.message.answer(
            "📭 У вас пока нет привычек.\nДобавьте их командой /habits."
        )
        return
    await call.message.answer(
        checklist_header(call.from_user.id),
        reply_markup=kb,
        parse_mode="HTML",
    )


@dp.callback_query(F.data == "map")
async def cb_map(call: CallbackQuery):
    await call.answer()
    await call.message.answer(
        f"<pre>{map_text(call.from_user.id)}</pre>",
        parse_mode="HTML",
    )


@dp.callback_query(F.data == "sleep")
async def cb_sleep(call: CallbackQuery):
    await call.answer()
    await call.message.answer(
        "Планы на сегодня завершены, статистика по сегодняшнему дню:\n\n"
        f"{today_stats_text(call.from_user.id)}"
    )


@dp.callback_query(F.data == "add_habit")
async def cb_add_habit(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await state.clear()
    await call.message.answer(
        "➕ Добавим новую привычку.\n\n"
        "Шаг 1 из 2. Введите название привычки.\n\n"
        "Для отмены — /cancel."
    )
    await state.set_state(HabitFSM.waiting_name)


#  ЗАПУСК

async def main():
    load_data()
    logging.info("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())