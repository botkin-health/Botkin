#!/usr/bin/env python3
"""
Валидатор данных HealthVault
Проверяет полноту и корректность данных перед анализом
"""

import xml.etree.ElementTree as ET
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Tuple

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

class HealthDataValidator:
    def __init__(self):
        self.project_root = Path(__file__).parent.parent
        self.data_path = self.project_root / "data"
        self.apple_health_xml = self.data_path / "apple-health" / "export.xml"
        self.nutrition_log = self.data_path / "nutrition" / "nutrition_log.json"
        
        self.validation_results = {
            'export_freshness': None,
            'data_sources': {},
            'incomplete_days': [],
            'missing_data_types': [],
            'critical_issues': [],
            'warnings': []
        }
    
    def validate_all(self) -> Dict:
        """Запускает полную валидацию всех данных"""
        logger.info("🔍 Начинаем полную валидацию данных HealthVault...")
        
        try:
            # 1. Проверка экспорта Apple Health
            self._validate_export_freshness()
            
            # 2. Проверка источников данных
            self._validate_data_sources()
            
            # 3. Проверка тренировок
            self._validate_workout_data()
            
            # 4. Проверка состава тела
            self._validate_body_composition()
            
            # 5. Проверка данных питания
            self._validate_nutrition_data()
            
            # 6. Проверка данных сна
            self._validate_sleep_data()
            
            # 7. Финальная оценка
            self._generate_final_assessment()
            
        except Exception as e:
            self.validation_results['critical_issues'].append(f"Критическая ошибка валидации: {e}")
            logger.error(f"Критическая ошибка валидации: {e}")
        
        return self.validation_results
    
    def _validate_export_freshness(self):
        """Проверяет свежесть экспорта Apple Health"""
        if not self.apple_health_xml.exists():
            self.validation_results['critical_issues'].append("❌ Файл экспорта Apple Health не найден!")
            return
            
        try:
            context = ET.iterparse(str(self.apple_health_xml), events=('start', 'end'))
            context = iter(context)
            event, root = next(context)
            
            export_date = None
            for event, elem in context:
                if event == 'end' and elem.tag == 'ExportDate':
                    export_date = elem.get('value')
                    break
                elem.clear()
            root.clear()
            
            if export_date:
                try:
                    export_dt = datetime.strptime(export_date, '%Y-%m-%d %H:%M:%S %z')
                except ValueError:
                    # Fallback to isoformat if strptime fails
                    export_dt = datetime.fromisoformat(export_date.replace('Z', '+00:00'))
                days_ago = (datetime.now(export_dt.tzinfo) - export_dt).days
                
                self.validation_results['export_freshness'] = {
                    'date': export_date,
                    'days_ago': days_ago
                }
                
                if days_ago > 7:
                    self.validation_results['critical_issues'].append(f"❌ Экспорт Apple Health устарел ({days_ago} дней)")
                elif days_ago > 3:
                    self.validation_results['warnings'].append(f"⚠️ Экспорт Apple Health старше 3 дней ({days_ago} дней)")
                else:
                    logger.info(f"✅ Экспорт Apple Health свежий ({days_ago} дней назад)")
            else:
                self.validation_results['warnings'].append("⚠️ Не удалось определить дату экспорта")
                
        except Exception as e:
            self.validation_results['warnings'].append(f"⚠️ Ошибка проверки даты экспорта: {e}")
    
    def _validate_data_sources(self):
        """Проверяет наличие данных от ключевых источников"""
        expected_sources = {
            'Zepp Life': 'Умные весы (состав тела)',
            'Connect': 'Garmin Connect (тренировки, активность)', 
            'Sleep Cycle': 'SleepCycle (детальный анализ сна)',
            'HealthVault Tracker': 'Telegram бот (питание)'
        }
        
        if not self.apple_health_xml.exists():
            return
            
        try:
            context = ET.iterparse(str(self.apple_health_xml), events=('start', 'end'))
            context = iter(context)
            event, root = next(context)
            
            found_sources = defaultdict(int)
            
            for event, elem in context:
                if event == 'end' and elem.tag == 'Record':
                    source = elem.get('sourceName')
                    if source:
                        found_sources[source] += 1
                elem.clear()
            root.clear()
            
            self.validation_results['data_sources'] = dict(found_sources)
            
            # Проверяем наличие ключевых источников
            for source, description in expected_sources.items():
                if source in found_sources:
                    logger.info(f"✅ {source}: {found_sources[source]:,} записей ({description})")
                else:
                    self.validation_results['warnings'].append(f"⚠️ Нет данных от {source} ({description})")
                    
        except Exception as e:
            self.validation_results['warnings'].append(f"⚠️ Ошибка проверки источников: {e}")
    
    def _validate_workout_data(self):
        """Проверяет данные о тренировках"""
        if not self.apple_health_xml.exists():
            return
            
        try:
            context = ET.iterparse(str(self.apple_health_xml), events=('start', 'end'))
            context = iter(context)
            event, root = next(context)
            
            workout_types = defaultdict(int)
            recent_workouts = []
            
            # Ищем записи тренировок и активности в фитнес оборудовании
            for event, elem in context:
                if event == 'end':
                    if elem.tag == 'Workout':
                        workout_type = elem.get('workoutActivityType')
                        start_date = elem.get('startDate')
                        if workout_type and start_date:
                            workout_types[workout_type] += 1
                            try:
                                date_obj = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                                if date_obj >= datetime.now(date_obj.tzinfo) - timedelta(days=30):
                                    recent_workouts.append({
                                        'type': workout_type,
                                        'date': date_obj.strftime('%Y-%m-%d'),
                                        'duration': elem.get('duration')
                                    })
                            except:
                                continue
                    
                    elif elem.tag == 'Record':
                        # Проверяем записи активности (может быть кроссфит записан как активность)
                        record_type = elem.get('type')
                        source = elem.get('sourceName')
                        if record_type and 'Activity' in record_type and source in ['Connect', 'Garmin Connect']:
                            start_date = elem.get('startDate')
                            if start_date:
                                try:
                                    date_obj = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                                    if date_obj >= datetime.now(date_obj.tzinfo) - timedelta(days=30):
                                        recent_workouts.append({
                                            'type': f"Activity ({source})",
                                            'date': date_obj.strftime('%Y-%m-%d'),
                                            'source': source
                                        })
                                except:
                                    continue
                elem.clear()
            root.clear()
            
            # Анализируем результаты
            total_workouts_30_days = len(recent_workouts)
            
            if total_workouts_30_days == 0:
                self.validation_results['critical_issues'].append("❌ Нет данных о тренировках за 30 дней!")
            elif total_workouts_30_days < 8:  # Менее 2 раз в неделю
                self.validation_results['warnings'].append(f"⚠️ Мало тренировок: {total_workouts_30_days} за 30 дней (ожидается 12+)")
            else:
                logger.info(f"✅ Тренировки найдены: {total_workouts_30_days} за 30 дней")
            
            # Сохраняем детали для отчета
            self.validation_results['workouts'] = {
                'total_30_days': total_workouts_30_days,
                'types': dict(workout_types),
                'recent': recent_workouts[-10:]  # Последние 10
            }
            
        except Exception as e:
            self.validation_results['warnings'].append(f"⚠️ Ошибка проверки тренировок: {e}")
    
    def _validate_body_composition(self):
        """Проверяет данные состава тела от умных весов"""
        if not self.apple_health_xml.exists():
            return
            
        try:
            context = ET.iterparse(str(self.apple_health_xml), events=('start', 'end'))
            context = iter(context)
            event, root = next(context)
            
            body_types = {
                'HKQuantityTypeIdentifierBodyMass': 'Вес',
                'HKQuantityTypeIdentifierBodyFatPercentage': 'Процент жира',
                'HKQuantityTypeIdentifierLeanBodyMass': 'Тощая масса',
                'HKQuantityTypeIdentifierBodyMassIndex': 'ИМТ'
            }
            
            found_body_data = defaultdict(int)
            recent_measurements = []
            
            for event, elem in context:
                if event == 'end' and elem.tag == 'Record':
                    record_type = elem.get('type')
                    source = elem.get('sourceName')
                    
                    if record_type in body_types and source == 'Zepp Life':
                        found_body_data[record_type] += 1
                        
                        start_date = elem.get('startDate')
                        if start_date:
                            try:
                                date_obj = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                                if date_obj >= datetime.now(date_obj.tzinfo) - timedelta(days=7):
                                    recent_measurements.append({
                                        'type': body_types[record_type],
                                        'date': date_obj.strftime('%Y-%m-%d %H:%M'),
                                        'value': elem.get('value')
                                    })
                            except:
                                continue
                elem.clear()
            root.clear()
            
            # Проверяем полноту данных
            missing_body_metrics = []
            for metric_type, metric_name in body_types.items():
                if found_body_data[metric_type] == 0:
                    missing_body_metrics.append(metric_name)
            
            if missing_body_metrics:
                self.validation_results['warnings'].append(f"⚠️ Нет данных: {', '.join(missing_body_metrics)}")
            
            recent_days = len(set(m['date'][:10] for m in recent_measurements))
            if recent_days < 3:
                self.validation_results['warnings'].append(f"⚠️ Мало измерений состава тела: {recent_days} дней за неделю")
            else:
                logger.info(f"✅ Состав тела: измерения за {recent_days} дней на неделе")
            
            self.validation_results['body_composition'] = {
                'found_metrics': {body_types[k]: v for k, v in found_body_data.items() if v > 0},
                'recent_days': recent_days,
                'total_measurements': sum(found_body_data.values())
            }
            
        except Exception as e:
            self.validation_results['warnings'].append(f"⚠️ Ошибка проверки состава тела: {e}")
    
    def _validate_nutrition_data(self):
        """Проверяет данные питания"""
        if not self.nutrition_log.exists():
            self.validation_results['warnings'].append("⚠️ Файл лога питания не найден")
            return
            
        try:
            with open(self.nutrition_log, 'r', encoding='utf-8') as f:
                nutrition_data = json.load(f)
            
            entries = nutrition_data.get('entries', [])
            if not entries:
                self.validation_results['warnings'].append("⚠️ Нет записей в логе питания")
                return
            
            # Анализируем последние 14 дней
            cutoff_date = datetime.now() - timedelta(days=14)
            recent_entries = []
            incomplete_days = []
            
            for entry in entries:
                try:
                    entry_date = datetime.strptime(entry['date'], '%Y-%m-%d')
                    if entry_date >= cutoff_date:
                        recent_entries.append(entry)
                        
                        # Проверяем полноту дня
                        meals = entry.get('meals', [])
                        total_calories = entry['totals'].get('calories', 0)
                        
                        # День считается неполным если:
                        # 1. Менее 2 приемов пищи И менее 1200 ккал
                        # 2. Или это сегодня и последний прием пищи был рано
                        is_today = entry_date.date() == datetime.now().date()
                        
                        if is_today:
                            current_hour = datetime.now().hour
                            if meals:
                                last_meal_time = meals[-1]['time']
                                last_hour = int(last_meal_time.split(':')[0])
                                if len(meals) == 1 and current_hour > 15 and last_hour < 12:
                                    incomplete_days.append(entry['date'] + " (только завтрак)")
                            elif current_hour > 12:
                                incomplete_days.append(entry['date'] + " (нет данных)")
                        elif len(meals) < 2 and total_calories < 1200:
                            incomplete_days.append(entry['date'] + " (мало данных)")
                            
                except ValueError:
                    continue
            
            self.validation_results['incomplete_days'] = incomplete_days
            
            if len(incomplete_days) > 3:
                self.validation_results['warnings'].append(f"⚠️ Много неполных дней питания: {len(incomplete_days)}")
            elif incomplete_days:
                logger.info(f"ℹ️ Неполные дни питания: {len(incomplete_days)} ({', '.join(incomplete_days)})")
            else:
                logger.info("✅ Данные питания полные")
            
            self.validation_results['nutrition'] = {
                'recent_entries': len(recent_entries),
                'incomplete_days_count': len(incomplete_days),
                'avg_calories': sum(e['totals'].get('calories', 0) for e in recent_entries) / len(recent_entries) if recent_entries else 0
            }
            
        except Exception as e:
            self.validation_results['warnings'].append(f"⚠️ Ошибка проверки питания: {e}")
    
    def _validate_sleep_data(self):
        """Проверяет данные сна"""
        if not self.apple_health_xml.exists():
            return
            
        try:
            context = ET.iterparse(str(self.apple_health_xml), events=('start', 'end'))
            context = iter(context)
            event, root = next(context)
            
            sleep_sources = defaultdict(int)
            recent_sleep = []
            
            for event, elem in context:
                if event == 'end' and elem.tag == 'Record':
                    record_type = elem.get('type')
                    if 'Sleep' in record_type:
                        source = elem.get('sourceName')
                        start_date = elem.get('startDate')
                        
                        sleep_sources[source] += 1
                        
                        if start_date:
                            try:
                                date_obj = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                                if date_obj >= datetime.now(date_obj.tzinfo) - timedelta(days=7):
                                    recent_sleep.append({
                                        'source': source,
                                        'date': date_obj.strftime('%Y-%m-%d'),
                                        'type': record_type
                                    })
                            except:
                                continue
                elem.clear()
            root.clear()
            
            if not sleep_sources:
                self.validation_results['warnings'].append("⚠️ Данные сна не найдены")
            else:
                logger.info(f"✅ Данные сна найдены: {len(sleep_sources)} источников")
                
                # Проверяем качество данных
                recent_days = len(set(s['date'] for s in recent_sleep))
                if recent_days < 5:
                    self.validation_results['warnings'].append(f"⚠️ Мало данных сна: {recent_days} дней за неделю")
            
            self.validation_results['sleep'] = {
                'sources': dict(sleep_sources),
                'recent_days': len(set(s['date'] for s in recent_sleep)),
                'total_records': sum(sleep_sources.values())
            }
            
        except Exception as e:
            self.validation_results['warnings'].append(f"⚠️ Ошибка проверки сна: {e}")
    
    def _generate_final_assessment(self):
        """Генерирует финальную оценку качества данных"""
        critical_count = len(self.validation_results['critical_issues'])
        warning_count = len(self.validation_results['warnings'])
        
        if critical_count > 0:
            self.validation_results['overall_status'] = 'КРИТИЧНО'
            self.validation_results['recommendation'] = 'НЕ ПРОВОДИТЬ анализ до устранения критических проблем'
        elif warning_count > 3:
            self.validation_results['overall_status'] = 'ПРЕДУПРЕЖДЕНИЕ'  
            self.validation_results['recommendation'] = 'Анализ возможен, но указать ограничения в отчете'
        else:
            self.validation_results['overall_status'] = 'ХОРОШО'
            self.validation_results['recommendation'] = 'Данные готовы к анализу'
    
    def print_summary(self):
        """Выводит краткий отчет валидации"""
        results = self.validation_results
        
        print("\n" + "="*60)
        print("📊 ОТЧЕТ ВАЛИДАЦИИ ДАННЫХ HEALTHVAULT")
        print("="*60)
        
        # Общий статус
        status = results.get('overall_status', 'НЕИЗВЕСТНО')
        if status == 'КРИТИЧНО':
            print(f"🚨 СТАТУС: {status}")
        elif status == 'ПРЕДУПРЕЖДЕНИЕ':
            print(f"⚠️ СТАТУС: {status}")
        else:
            print(f"✅ СТАТУС: {status}")
        
        print(f"💡 РЕКОМЕНДАЦИЯ: {results.get('recommendation', 'Н/Д')}")
        
        # Критические проблемы
        if results['critical_issues']:
            print(f"\n🚨 КРИТИЧЕСКИЕ ПРОБЛЕМЫ ({len(results['critical_issues'])}):")
            for issue in results['critical_issues']:
                print(f"   {issue}")
        
        # Предупреждения
        if results['warnings']:
            print(f"\n⚠️ ПРЕДУПРЕЖДЕНИЯ ({len(results['warnings'])}):")
            for warning in results['warnings']:
                print(f"   {warning}")
        
        # Краткая статистика
        print(f"\n📊 КРАТКАЯ СТАТИСТИКА:")
        
        if 'export_freshness' in results and results['export_freshness']:
            days_ago = results['export_freshness']['days_ago']
            print(f"   • Экспорт Apple Health: {days_ago} дней назад")
        
        if 'workouts' in results:
            workouts = results['workouts']['total_30_days']
            print(f"   • Тренировки (30 дней): {workouts}")
        
        if 'body_composition' in results:
            measurements = results['body_composition']['total_measurements']
            print(f"   • Измерения состава тела: {measurements:,}")
        
        if 'nutrition' in results:
            entries = results['nutrition']['recent_entries']
            print(f"   • Записи питания (14 дней): {entries}")
        
        if 'sleep' in results:
            sources = len(results['sleep']['sources'])
            print(f"   • Источники данных сна: {sources}")
        
        print("\n" + "="*60)
        
        return results.get('overall_status') == 'ХОРОШО'

def main():
    """Запуск валидации"""
    validator = HealthDataValidator()
    results = validator.validate_all()
    
    # Выводим отчет
    is_ready = validator.print_summary()
    
    # Сохраняем результаты
    results_file = validator.project_root / "logs" / f"validation_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    results_file.parent.mkdir(exist_ok=True)
    
    with open(results_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    
    print(f"\n💾 Отчет сохранен: {results_file}")
    
    return is_ready

if __name__ == "__main__":
    main()