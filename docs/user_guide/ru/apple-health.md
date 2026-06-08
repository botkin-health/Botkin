# 🍎 Apple Health — подключение iPhone / Apple Watch / тонометра / весов

> Через одно приложение Health Auto Export (HAE) на iPhone к нам автоматически приходят шаги, пульс, сон, HRV, вес с весов, давление с тонометра — всё что есть в Apple Health.

## Что синхронизируется

| Метрика | Источник в твоём iPhone | Куда пишется на нашем сервере |
|---|---|---|
| Шаги, дистанция, активные ккал, этажи | Apple Watch / iPhone | `activity_log` |
| Пульс (avg/min/max), пульс покоя | Apple Watch / умные тонометры | `activity_log` + `raw_data` |
| Давление (систолическое/диастолическое) | Omron Connect → Apple Health | `blood_pressure_logs` |
| Походка (скорость, длина шага, асимметрия) | iPhone | `activity_log.raw_data` |
| Вес, % жира, мышечная масса | Mi-весы / Withings → Apple Health | `weights` |
| VO2 Max, температура запястья | Apple Watch | `activity_log.raw_data` |
| Сон (часы, фазы) | Apple Watch | `activity_log` |
| HRV (SDNN) | Apple Watch | `activity_log` |
| SpO2 | Apple Watch | `activity_log` |

То есть **всё что попадает в Apple Health** — попадает к нам, без ручного ввода.

## Как настроить (один раз)

### Шаг 1 — поставь приложение Health Auto Export (HAE)

[App Store: Health Auto Export – JSON+CSV](https://apps.apple.com/app/health-auto-export-json-csv/id1115567069)

Стоит $24.99 один раз (lifetime). Бесплатной версии для нашей задачи не хватает (нужен REST API, он только в Pro).

### Шаг 2 — получи свой Apple Health токен в боте

В чате с [@Botkin_md_bot](https://t.me/Botkin_md_bot) напиши:

```
/health_token
```

Бот ответит длинной строкой вида:
```
hvt_895655_a1b2c3d4e5f6...
```

Этот токен — твой персональный ключ для HAE.

### Шаг 3 — настрой автоматизацию в HAE

В приложении HAE:

1. **Add Automation** → **REST API**
2. **URL:** `https://botkin.health/apple_health_v2`
3. **HTTP Method:** POST
4. **Header:** добавить `Authorization` со значением `Bearer hvt_895655_твой_токен`
5. **Format:** JSON · **Version:** v2
6. **Range:** Yesterday
7. **Aggregate:** ON
8. **Group by:** Day
9. **Frequency:** 1 / Days

10. **Выбери метрики** (галочки):
    - Steps
    - Distance Walking/Running
    - Active Energy
    - Resting Heart Rate
    - Heart Rate (Avg/Min/Max)
    - Blood Pressure Systolic / Diastolic
    - Walking Speed
    - Walking Step Length
    - Walking Double Support Percentage
    - Walking Asymmetry Percentage
    - Body Mass
    - Body Fat Percentage
    - Lean Body Mass
    - VO2 Max
    - Respiratory Rate
    - Wrist Temperature
    - Flights Climbed

### Шаг 4 — проверь ручной экспорт

В HAE внизу есть зелёная кнопка **«Manual Export»** — нажми её, выбери диапазон (например, последние 7 дней), HAE отправит данные сразу.

Проверь в боте: открой Mini-app → Дневник → должны появиться шаги/калории за последние дни.

## Как это работает дальше

После настройки **больше ничего делать не надо**. iOS-планировщик HAE срабатывает раз в сутки (обычно ночью когда iPhone на зарядке) и шлёт данные за вчерашний день.

**Требования:**
- iPhone разблокирован хотя бы раз в день
- Background App Refresh для HAE включён в Настройках iPhone
- Low Power Mode выключен (он блокирует фоновые задачи)

**Когда увидишь данные:** обычно к утру следующего дня у тебя в дашборде свежие вчерашние шаги и пульс.

## Подключение тонометра Omron к Apple Health

Если хочешь автоматический синк АД (а не фотать каждое измерение боту):

1. Поставь приложение **Omron Connect** на iPhone
2. Спарь тонометр через Bluetooth
3. В Omron Connect → Settings → разреши синхронизацию с Apple Health
4. После каждого замера: тонометр → Bluetooth → Omron Connect → Apple Health → (ночью) → HAE → наш сервер

Аналогично для других тонометров (Withings, Beurer и т.д.) — главное чтобы было приложение которое пишет в Apple Health.

## Подключение Mi-весов / Xiaomi Body Composition

1. Mi Fitness app (бывшая Mi Fit) на iPhone
2. Настрой связь с Apple Health (отдай вес, % жира, мышечную массу, висцеральный жир)
3. После каждого взвешивания → Mi Fitness → Apple Health → HAE → наш сервер

То же самое для Withings весов и любых других, которые умеют писать в Apple Health.

## Если что-то не работает

| Проблема | Решение |
|---|---|
| HAE говорит «401 Unauthorized» | Токен не тот. Перевыпусти через `/health_token rotate` в боте |
| Данные не приходят день за днём | Background App Refresh выключен в iOS Settings → General → BAR |
| Часть метрик не появляется | В HAE → Automation → проверь что эти метрики выбраны галочками |
| Шаги дублируются с Garmin | Если у тебя оба: Garmin Connect и Apple Watch — выключи в одном источнике метрику. Garmin приоритет если ты бегун |
| HAE упал / переустановил приложение | Re-настрой автоматизацию заново. Токен в боте не меняется. |

## Какие данные в нашей БД

После синка ты увидишь данные:
- В **Mini-app** → Дневник (шаги и калории за день)
- В **Dashboard** (тренды весом, пульса, давления, активности)
- AI-помощник в боте использует эти данные при ответах на твои вопросы

## Связанные разделы

- [Безопасность](./security.md) — про health_token и как его отозвать
- [Mini-app](./mini-app.md) — где увидеть синкнутые данные
- [Dashboard](./dashboard.md) — графики и тренды
