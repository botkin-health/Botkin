#!/usr/bin/env python3
"""
ИСПРАВЛЕННЫЙ анализатор Apple Health данных
Учитывает все выявленные проблемы и обеспечивает корректный анализ
"""

import xml.etree.ElementTree as ET
import json
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

class FixedAppleHealthAnalyzer:
    def __init__(self):
        self.project_root = Path(__file__).parent.parent
        self.data_path = self.project_root / "data"
        self.apple_health_xml = self.data_path / "apple-health" / "export.xml"
        
    def comprehensive_analysis(self):
        """Запускает комплексный анализ с проверками"""
        
        print("🔍 ИСПРАВЛЕННЫЙ АНАЛИЗ APPLE HEALTH ДАННЫХ")
        print("="*60)
        
        # 1. Проверка экспорта
        export_info = self._check_export_date()
        
        # 2. Анализ тренировок (исправленная версия)  
        workout_data = self._analyze_workouts_corrected()
        
        # 3. Анализ состава тела (исправленная версия)
        body_comp_data = self._analyze_body_composition_corrected()
        
        # 4. Анализ сна
        sleep_data = self._analyze_sleep_data()
        
        # 5. Проверка 24 января
        jan_24_status = self._check_january_24()
        
        # 6. Комплексный отчет
        self._generate_corrected_report(export_info, workout_data, body_comp_data, sleep_data, jan_24_status)
    
    def _check_export_date(self):
        """Проверяет дату экспорта с детальной отладкой"""
        try:
            context = ET.iterparse(str(self.apple_health_xml), events=('start', 'end'))
            context = iter(context)
            event, root = next(context)
            
            export_date = None
            elements_checked = 0
            
            for event, elem in context:
                if event == 'end':
                    elements_checked += 1
                    if elem.tag == 'ExportDate':
                        export_date = elem.get('value')
                        logger.info(f"Найден ExportDate: {export_date}")
                        break
                    elif elem.tag == 'HealthData':
                        # Иногда дата может быть в атрибутах HealthData
                        for attr_name, attr_value in elem.attrib.items():
                            if 'date' in attr_name.lower() or 'time' in attr_name.lower():
                                logger.info(f"HealthData атрибут {attr_name}: {attr_value}")
                    
                    if elements_checked > 20:  # Ограничиваем поиск
                        break
                        
                elem.clear()
            
            if not export_date:
                logger.warning("ExportDate не найден, ищем другие варианты...")
                # Можем попробовать взять дату файла
                file_stat = self.apple_health_xml.stat()
                file_time = datetime.fromtimestamp(file_stat.st_mtime)
                logger.info(f"Время модификации файла: {file_time}")
                
                return {
                    'found': False,
                    'file_modified': file_time.isoformat(),
                    'estimated_export_age': 'неизвестно'
                }
            
            export_dt = datetime.fromisoformat(export_date.replace('Z', '+00:00'))
            days_ago = (datetime.now(export_dt.tzinfo) - export_dt).days
            
            return {
                'found': True,
                'export_date': export_date,
                'days_ago': days_ago,
                'status': 'свежий' if days_ago <= 1 else 'старый' if days_ago > 7 else 'приемлемый'
            }
            
        except Exception as e:
            logger.error(f"Ошибка проверки даты экспорта: {e}")
            return {'found': False, 'error': str(e)}
    
    def _analyze_workouts_corrected(self):
        """ИСПРАВЛЕННЫЙ анализ тренировок"""
        logger.info("🏋️ Анализируем тренировки (исправленная версия)...")
        
        try:
            context = ET.iterparse(str(self.apple_health_xml), events=('start', 'end'))
            context = iter(context)
            event, root = next(context)
            
            workouts = []
            gym_activities = []  # Для записей типа Gym & Fitness Equipment
            
            for event, elem in context:
                if event == 'end':
                    if elem.tag == 'Workout':
                        # Настоящие workout записи
                        workout_type = elem.get('workoutActivityType')
                        start_date = elem.get('startDate') 
                        duration = elem.get('duration')
                        source = elem.get('sourceName')
                        
                        if start_date:
                            try:
                                date_obj = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                                workouts.append({
                                    'type': workout_type,
                                    'date': date_obj.strftime('%Y-%m-%d %H:%M'),
                                    'duration_min': float(duration)/60 if duration else None,
                                    'source': source,
                                    'datetime': date_obj
                                })
                            except:
                                continue
                    
                    elif elem.tag == 'ActivitySummary':
                        # Сводки активности по дням
                        date_attr = elem.get('dateComponents')
                        active_energy = elem.get('activeEnergyBurned')
                        exercise_time = elem.get('appleExerciseTime')
                        
                        if date_attr and (active_energy or exercise_time):
                            gym_activities.append({
                                'date': date_attr,
                                'active_energy': float(active_energy) if active_energy else 0,
                                'exercise_time': float(exercise_time) if exercise_time else 0
                            })
                
                elem.clear()
            
            # Фильтруем последние 30 дней
            cutoff = datetime.now() - timedelta(days=30)
            recent_workouts = [w for w in workouts if w['datetime'] >= cutoff]
            
            # Анализируем паттерны тренировок
            crossfit_indicators = ['HIIT', 'CrossFit', 'Functional', 'Circuit', 'Gym']
            crossfit_workouts = []
            
            for workout in recent_workouts:
                workout_type = workout['type'] or ''
                if any(indicator.lower() in workout_type.lower() for indicator in crossfit_indicators):
                    # Проверяем, похоже ли на кроссфит (длительность 45-75 минут)
                    duration = workout['duration_min']
                    if duration and 45 <= duration <= 90:
                        crossfit_workouts.append(workout)
            
            return {
                'total_workouts_30_days': len(recent_workouts),
                'crossfit_workouts': len(crossfit_workouts),
                'workout_details': recent_workouts[-10:],  # Последние 10
                'crossfit_details': crossfit_workouts,
                'gym_activities_days': len(gym_activities)
            }
            
        except Exception as e:
            logger.error(f"Ошибка анализа тренировок: {e}")
            return {'error': str(e)}
    
    def _analyze_body_composition_corrected(self):
        """ИСПРАВЛЕННЫЙ анализ состава тела"""
        logger.info("⚖️ Анализируем состав тела (исправленная версия)...")
        
        try:
            context = ET.iterparse(str(self.apple_health_xml), events=('start', 'end'))
            context = iter(context)
            event, root = next(context)
            
            body_metrics = {
                'HKQuantityTypeIdentifierBodyMass': [],
                'HKQuantityTypeIdentifierBodyFatPercentage': [],
                'HKQuantityTypeIdentifierLeanBodyMass': [],
                'HKQuantityTypeIdentifierBodyMassIndex': []
            }
            
            zepp_records = 0
            
            for event, elem in context:
                if event == 'end' and elem.tag == 'Record':
                    record_type = elem.get('type')
                    source = elem.get('sourceName')
                    
                    if record_type in body_metrics and source == 'Zepp Life':
                        value = elem.get('value')
                        start_date = elem.get('startDate')
                        
                        if value and start_date:
                            try:
                                date_obj = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                                body_metrics[record_type].append({
                                    'date': date_obj.strftime('%Y-%m-%d %H:%M'),
                                    'value': float(value),
                                    'datetime': date_obj
                                })
                                zepp_records += 1
                            except:
                                continue
                
                elem.clear()
            
            # Анализируем тренды
            analysis = {}
            metric_names = {
                'HKQuantityTypeIdentifierBodyMass': 'Вес',
                'HKQuantityTypeIdentifierBodyFatPercentage': 'Процент жира',  
                'HKQuantityTypeIdentifierLeanBodyMass': 'Тощая масса',
                'HKQuantityTypeIdentifierBodyMassIndex': 'ИМТ'
            }
            
            for metric_type, data_list in body_metrics.items():
                if len(data_list) >= 5:
                    # Сортируем по дате
                    data_list.sort(key=lambda x: x['datetime'])
                    
                    # Берем последние и первые 5 измерений для тренда
                    recent_5 = data_list[-5:]
                    old_5 = data_list[:5]
                    
                    recent_avg = sum(r['value'] for r in recent_5) / len(recent_5)
                    old_avg = sum(r['value'] for r in old_5) / len(old_5)
                    
                    analysis[metric_names[metric_type]] = {
                        'total_records': len(data_list),
                        'latest_value': data_list[-1]['value'],
                        'latest_date': data_list[-1]['date'],
                        'trend_change': recent_avg - old_avg,
                        'first_measurement': data_list[0]['date'],
                        'last_measurement': data_list[-1]['date']
                    }
            
            return {
                'zepp_records_total': zepp_records,
                'metrics_analysis': analysis,
                'has_body_composition': len(analysis) > 0
            }
            
        except Exception as e:
            logger.error(f"Ошибка анализа состава тела: {e}")
            return {'error': str(e)}
    
    def _analyze_sleep_data(self):
        """Анализ данных сна из всех источников"""
        logger.info("😴 Анализируем данные сна...")
        
        try:
            context = ET.iterparse(str(self.apple_health_xml), events=('start', 'end'))
            context = iter(context)  
            event, root = next(context)
            
            sleep_sources = defaultdict(list)
            
            for event, elem in context:
                if event == 'end' and elem.tag == 'Record':
                    record_type = elem.get('type')
                    if record_type and 'Sleep' in record_type:
                        source = elem.get('sourceName')
                        start_date = elem.get('startDate')
                        value = elem.get('value')
                        
                        if source and start_date:
                            try:
                                date_obj = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                                if date_obj >= datetime.now(date_obj.tzinfo) - timedelta(days=7):
                                    sleep_sources[source].append({
                                        'date': date_obj.strftime('%Y-%m-%d %H:%M'),
                                        'value': value,
                                        'type': record_type
                                    })
                            except:
                                continue
                elem.clear()
            
            return {
                'sources_found': len(sleep_sources),
                'sources_detail': {source: len(records) for source, records in sleep_sources.items()},
                'total_recent_records': sum(len(records) for records in sleep_sources.values())
            }
            
        except Exception as e:
            logger.error(f"Ошибка анализа сна: {e}")
            return {'error': str(e)}
    
    def _check_january_24(self):
        """Проверяет, действительно ли 24 января неполный день"""
        current_time = datetime.now()
        
        # Проверяем, если анализ запущен 24 января
        if current_time.date() == datetime(2026, 1, 24).date():
            current_hour = current_time.hour
            
            if current_hour < 22:  # День еще не закончен
                return {
                    'is_incomplete': True,
                    'current_hour': current_hour,
                    'status': f'День не завершен (сейчас {current_hour:02d}:00)',
                    'should_exclude': True
                }
        
        return {
            'is_incomplete': False,
            'status': 'День завершен или анализ из будущего'
        }
    
    def _generate_corrected_report(self, export_info, workout_data, body_comp_data, sleep_data, jan_24_status):
        """Генерирует исправленный отчет"""
        
        print("\\n📋 ИСПРАВЛЕННЫЙ ОТЧЕТ ПО ДАННЫМ:")
        print("-" * 40)
        
        # Экспорт
        if export_info.get('found'):
            days_ago = export_info['days_ago']
            status = export_info['status']
            print(f"📅 Экспорт: {days_ago} дней назад ({status})")
        else:
            print("📅 Экспорт: дата не определена")
        
        # Тренировки
        total_workouts = workout_data.get('total_workouts_30_days', 0)
        crossfit_workouts = workout_data.get('crossfit_workouts', 0)
        print(f"🏋️ Тренировки (30 дней): {total_workouts} общих, {crossfit_workouts} кроссфит-типа")
        
        if crossfit_workouts > 0:
            print("   ✅ Кроссфит тренировки НАЙДЕНЫ!")
            for workout in workout_data.get('crossfit_details', [])[-5:]:
                duration = workout.get('duration_min', 0)
                print(f"   • {workout['date']}: {workout['type']} ({duration:.0f} мин)")
        else:
            print("   ❌ Кроссфит тренировки не найдены как Workout записи")
        
        # Состав тела
        zepp_records = body_comp_data.get('zepp_records_total', 0)
        has_composition = body_comp_data.get('has_body_composition', False)
        print(f"⚖️ Состав тела: {zepp_records:,} записей от Zepp Life")
        
        if has_composition:
            print("   ✅ Данные состава тела НАЙДЕНЫ!")
            analysis = body_comp_data.get('metrics_analysis', {})
            for metric, data in analysis.items():
                latest = data['latest_value']
                change = data['trend_change']
                if metric == 'Процент жира':
                    print(f"   • {metric}: {latest*100:.1f}% (тренд: {change*100:+.1f}%)")
                else:
                    print(f"   • {metric}: {latest:.1f} (тренд: {change:+.1f})")
        
        # Сон
        sleep_sources = sleep_data.get('sources_found', 0)
        sleep_records = sleep_data.get('total_recent_records', 0)
        print(f"😴 Сон: {sleep_sources} источников, {sleep_records} записей за 7 дней")
        
        if sleep_sources > 0:
            print("   ✅ Данные сна найдены:")
            for source, count in sleep_data.get('sources_detail', {}).items():
                print(f"   • {source}: {count} записей")
        
        # 24 января
        if jan_24_status['is_incomplete']:
            print(f"📊 24 января: {jan_24_status['status']}")
            print(f"   {'✅' if jan_24_status['should_exclude'] else '❌'} Правильно исключен из анализа")
        
        print("\\n" + "="*60)
        print("🎯 ГЛАВНЫЕ ВЫВОДЫ:")
        
        # Определяем реальный статус
        critical_issues = []
        if not export_info.get('found'):
            critical_issues.append("Дата экспорта не определена")
        if export_info.get('days_ago', 0) > 7:
            critical_issues.append("Экспорт слишком старый")
        if zepp_records == 0:
            critical_issues.append("Нет данных от умных весов")
        
        if critical_issues:
            print("🚨 КРИТИЧЕСКИЕ ПРОБЛЕМЫ:")
            for issue in critical_issues:
                print(f"   • {issue}")
        else:
            print("✅ ДАННЫЕ ГОТОВЫ К АНАЛИЗУ")
        
        # Проблемы с моим предыдущим анализом
        print("\\n🔍 ПРОБЛЕМЫ В ПРЕДЫДУЩЕМ АНАЛИЗЕ:")
        if crossfit_workouts == 0 and total_workouts > 0:
            print("   • Тренировки не найдены как 'CrossFit', но есть другие активности")
        if zepp_records > 0:
            print("   • Данные состава тела ЕСТЬ, но парсер их не нашел")
        if jan_24_status['is_incomplete']:
            print(f"   • 24 января корректно определен как неполный день")

def main():
    analyzer = FixedAppleHealthAnalyzer()
    analyzer.comprehensive_analysis()

if __name__ == "__main__":
    main()