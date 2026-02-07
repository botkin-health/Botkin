"""Apple Health import and display handlers"""

from aiogram import Router, F
from aiogram.types import Message, FSInputFile
from aiogram.filters import Command
from aiogram import Bot
import zipfile
import tempfile
from pathlib import Path
import logging

from core.apple_health_parser import parse_export_xml, deduplicate_data
from database import SessionLocal
from database.crud import import_apple_health_data, get_latest_weight, get_latest_blood_pressure

router = Router()
logger = logging.getLogger(__name__)


@router.message(Command("import_health"))
async def cmd_import_health(message: Message, user_id: int):
    """Start health data import"""
    await message.answer(
        "📱 <b>Импорт Apple Health</b>\n\n"
        "Отправь мне export.zip из приложения Здоровье:\n\n"
        "1️⃣ Здоровье → Профиль (👤 правый верхний угол)\n"
        "2️⃣ Экспорт всех данных о здоровье\n"
        "3️⃣ Сохрани zip файл\n"
        "4️⃣ Отправь его сюда\n\n"
        "⏳ Импорт может занять 1-2 минуты для больших архивов\n"
        "💾 Поддерживаются: вес, давление, пульс, HRV, % жира",
        parse_mode='HTML'
    )


@router.message(F.document & (F.document.file_name.endswith('.zip') | F.document.file_name.contains('export')))
async def handle_health_export(message: Message, user_id: int, bot: Bot):
    """Process Apple Health export.zip"""
    
    # Check file size (Apple exports can be large)
    if message.document.file_size > 100 * 1024 * 1024:  # 100MB limit
        await message.answer("❌ Файл слишком большой (>100MB). Попробуй экспортировать данные за меньший период.")
        return
    
    status_msg = await message.answer("⏳ Загружаю файл...")
    
    try:
        # Download zip
        file = await bot.get_file(message.document.file_id)
        
        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = Path(tmpdir) / "export.zip"
            await bot.download_file(file.file_path, zip_path)
            
            # Extract
            await status_msg.edit_text("📦 Распаковываю архив...")
            try:
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(tmpdir)
            except zipfile.BadZipFile:
                await status_msg.edit_text("❌ Не валидный ZIP архив")
                return
            
            # Find export.xml
            xml_path = Path(tmpdir) / "apple_health_export" / "export.xml"
            
            if not xml_path.exists():
                # Try alternative paths
                xml_candidates = list(Path(tmpdir).rglob("export.xml"))
                if xml_candidates:
                    xml_path = xml_candidates[0]
                else:
                    await status_msg.edit_text("❌ Не найден export.xml в архиве")
                    return
            
            # Parse
            await status_msg.edit_text("🔍 Анализирую данные...")
            
            try:
                parsed_data = parse_export_xml(str(xml_path), user_id)
                
                # Deduplicate
                for key in parsed_data:
                    parsed_data[key] = deduplicate_data(parsed_data[key])
                
                # Import to DB
                await status_msg.edit_text("💾 Сохраняю в базу...")
                
                db = SessionLocal()
                try:
                    total_imported = 0
                    import_details = {}
                    
                    for data_type, records in parsed_data.items():
                        if records:
                            count = import_apple_health_data(db, user_id, records)
                            total_imported += count
                            if count > 0:
                                import_details[data_type] = count
                    
                    # Build report
                    if total_imported > 0:
                        report = f"✅ <b>Импорт завершён</b>\n\n"
                        report += f"📊 Загружено: <b>{total_imported}</b> новых записей\n\n"
                        
                        type_names = {
                            'weight': '⚖️ Вес',
                            'blood_pressure': '🩺 Давление',
                            'heart_rate': '❤️ Пульс',
                            'resting_heart_rate': '💙 Пульс покоя',
                            'hrv': '📈 HRV',
                            'body_fat': '📉 % жира'
                        }
                        
                        for data_type, count in import_details.items():
                            name = type_names.get(data_type, data_type)
                            report += f"{name}: {count}\n"
                        
                        report += f"\n💡 Используй /health для просмотра"
                        
                        await status_msg.edit_text(report, parse_mode='HTML')
                    else:
                        await status_msg.edit_text(
                            "ℹ️ Все данные уже были импортированы ранее\n\n"
                            "Используй /health для просмотра",
                            parse_mode='HTML'
                        )
                    
                finally:
                    db.close()
                    
            except Exception as e:
                logger.error(f"Parse error for user {user_id}: {e}", exc_info=True)
                await status_msg.edit_text(f"❌ Ошибка парсинга: {str(e)[:100]}")
                
    except Exception as e:
        logger.error(f"Import error for user {user_id}: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Ошибка импорта: {str(e)[:100]}")


@router.message(Command("health"))
async def cmd_health(message: Message, user_id: int):
    """Show health metrics summary"""
    
    db = SessionLocal()
    try:
        weight = get_latest_weight(db, user_id)
        bp = get_latest_blood_pressure(db, user_id)
        
        response = "🩺 <b>Показатели здоровья</b>\n\n"
        
        has_data = False
        
        if weight:
            has_data = True
            response += f"⚖️ <b>Вес:</b> {weight['value']} {weight['unit']}\n"
            response += f"   📅 {weight['date'].strftime('%d.%m.%Y %H:%M')}\n"
            response += f"   📱 {weight['source']}\n\n"
        
        if bp:
            has_data = True
            response += f"🩺 <b>Давление:</b> {bp['systolic']}/{bp['diastolic']} mmHg\n"
            response += f"   📅 {bp['date'].strftime('%d.%m.%Y %H:%M')}\n"
            response += f"   📱 {bp['source']}\n\n"
        
        if not has_data:
            response += "📭 Нет данных\n\n"
            response += "💡 Используй /import_health для загрузки данных из Apple Health"
        
        await message.answer(response, parse_mode='HTML')
        
    finally:
        db.close()
