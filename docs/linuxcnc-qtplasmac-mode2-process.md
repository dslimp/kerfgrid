# QtPlasmaC Mode 2 Controller Process

Source checked on 2026-08-27:
`https://www.linuxcnc.org/docs/devel/html/ru/plasma/qtplasmac.html`.

The physical controller is now `192.168.88.68` (reserved Wi-Fi lease), with GUI user `dslimp`, an
onboard LPT at `0x378` and QtPlasmaC Mode 2. Source configuration was extracted
from the working Mach3 installation into `tools/linuxcnc/plasma-machine-source.yml`;
physical deployment vars are in `tools/linuxcnc/physical-controller.yml`.
Do not replace source-derived mappings with guessed role defaults.

## Подготовка после ошибки контакта — 2026-10-13

При отключённом питании двигателей подготовлен отдельный физический профиль:
Z `STEP_SCALE=-1000`, ручной `HOME=HOME_OFFSET=35`, диапазон пока 0…50 мм.
Это настройка для проверки по наблюдению контакта при начальной команде Z45;
физическое направление и ход ещё не подтверждены. Исходные настройки Mach3
и профиль симулятора сохранены. По просьбе оператора скорости восстановлены
из Mach3: X/Y 7998 мм/мин, Z 642 мм/мин. Поиск F800 из старого макроса ограничен
прежним пределом Z642; setup/probe выставлены 642. Ускорения X/Y1000 и Z143 мм/с²
сохранены. Float Switch Travel=3 мм пока требует измерения.

После сообщения оператора о царапании соплом восстановлена высота старого M3:
`G0 Z8` без отдельного опускания перед движением. В материале 0 контроллера и
в стартовом профиле Fubag KerfGrid PH=CH=8 мм. Это начальная высота прежнего
макроса; внешний THC продолжает управлять высотой при резке. Прежние 3 мм
прожига и 1–1,5 мм реза заменены. Старые экспортированные файлы сохраняют
старые высоты: чертёж нужно экспортировать и отправить заново.

Добавлены кнопки **PROBE TEST** и **Ноль XYZ**. «Ноль XYZ» присваивает текущей
точке рабочие X=Y=Z=0 без движения, сохраняя машинную базу. После этого перед
резом QtPlasmaC всё равно ищет поверхность листа. Кнопка доступна при включённом
программном Machine, выполненном HOME и остановленной программе.

Справа от «Ноль XYZ» добавлена **GOTO HOME**. Она сначала выводит Z на высоту
подъезда программы (в текущем профиле машинная Z45), затем возвращает X/Y в
рабочие 0/0. Z остаётся поднятой; кнопка не меняет выставленный ноль и HOME.
STOP/Esc отменяет весь возврат, в том числе во время подъёма до начала XY.
Возврат выполняется одной подпрограммой; ручной режим включается после её
завершения или отмены, чтобы не обрывать последнее перемещение.

Порядок физической проверки с обесточенным плазморезом:

1. Проверить, что Esc не зажата: раньше проводная USB-клавиатура непрерывно
   посылала Esc и прерывала даже движение мышью. При последней проверке
   этот источник не обнаружен, изоляция клавиатуры не использовалась.
   Освободить сопло от стола и убедиться, что FLOAT отпустился.
2. На MAIN выбрать шаг 0,1 мм и малую скорость, проверить коротким джогом:
   +Z/PgUp поднимает горелку, −Z/PgDn опускает. При неверном направлении
   остановиться; подготовленную инверсию нельзя считать проверенной.
3. Измерить доступный ход Z и убедиться, что над выбранным исходным положением
   есть минимум 10 мм свободного подъёма. Концевиков осей нет; FLOAT — только
   датчик касания для поиска листа.
4. Стрелками выбрать начало раскроя, PgUp/PgDn — исходную высоту с зазором,
   нажать **HOME ALL**, затем **Ноль XYZ**. HOME здесь не двигает оси и назначает
   текущему месту внутренние X/Y=0, Z=35; рабочие координаты становятся 0/0/0.
   Начальная команда фильтра Z45 поднимет горелку на 10 мм. Отдельная постоянная
   машинная база не требуется. X/Y допускают движение в обе стороны от нуля
   (X ±1300, Y ±2250 мм); эти программные диапазоны не определяют физические упоры.
5. Над листом проверить **PROBE TEST**: спуск, срабатывание FLOAT, отпускание
   при подъёме, выход на высоту прожига. Общий таймер теста — 30 секунд с момента
   нажатия, включая поиск и подъём; затем горелка возвращается на исходную высоту.
   До окончания таймера измерить
   зазор и уточнить Float Travel, чтобы он соответствовал высоте прожига.
6. Выполнить OUTLINE и затем JOB с Torch Enable выключенным. JOB с M3 выполняет
   поиск листа и перемещения Z даже при выключенном Torch Enable.

Физическая проверка этой последовательности ещё не выполнена. Предыдущее
предупреждение realtime требует отдельной проверки перед настоящим резом.

Стенд с отключёнными двигателями и зажиганием прошёл удержание/отпускание всех
шести направлений клавиатурой и мышью, восстановление PgUp при активном FLOAT,
PROBE TEST и полный чертёж с двумя поисками листа за 90,22 секунды. FLOAT для
этих циклов имитировался и затем был подключён обратно к реальному LPT-входу.
Это предыдущий стенд с PH3/CH1,5; проводная клавиатура тогда временно
изолировалась на время теста. Результаты:
`../output/linuxcnc/physical/2026-10-13-bench-verification.json`.

После восстановления PH=CH=8 отдельно проверены GOTO HOME, отмена возврата
через Esc во время подъёма, PROBE TEST и полный JOB с двумя поисками листа
за 88,91 секунды. Виртуальный зазор прожига и начала реза 8,004…8,021 мм;
это программная проверка, реальный зазор сопла ещё нужно измерить.
Двигатели обесточены, зажигание выключено, реальный FLOAT подключён обратно.
Результаты: `../output/linuxcnc/physical/2026-10-13-height8-return-verification.json`.

## Первые резы: воздух, скос и врезка — 2026-10-15

Для Fubag PLASMA 40 со штатной FB P40 ориентир — 5 бар на регуляторе аппарата
при идущем воздухе в SET; после настройки вернуть RUN. Каталог Fubag 2018,
стр. 53, даёт FB P40 4,5–5 бар / 110 л/мин. Инструкция аппарата, раздел 5.1,
допускает 3,5–6 бар и требует очищенный сухой воздух. Это давление не задаётся
командой G-code. Старые сохранённые пользовательские таблицы сохраняют свои
значения; в стандартной стартовой таблице теперь 5 бар.

Инструкция, раздел 5.2, указывает расстояние сопло–металл порядка 3–4 мм.
PH=CH=8 восстановлены из старого макроса, а не из заводской таблицы резки.
Перед подбором высоты надо измерить реальный зазор после IHS и проверить
Float Travel. При включённом внешнем THC высота может меняться после старта:
значение CH на экране не доказывает фактический зазор во время реза.

На первом фото оператора кратер совпадает с ошибкой в CAM: касательная врезка
от (94,85;9,35) к вогнутой вершине (89,85;9,35) проходила по полезному металлу.
Исправлена сторона врезки для замкнутых путей; добавлена проверка самой детали.
Ранее сохранённые NGC надо экспортировать заново. Ручные точки прожига
сохраняются; их пересечения с полезным металлом показываются предупреждениями.

Две ровные кромки с гратом и две скошенные без него сами по себе не определяют
причину. Проверить перпендикулярность горелки листу в двух плоскостях, сопло
и электрод, затем сопоставить фактическую высоту и скорость. Для отделения
работы THC от геометрии полезен пробный квадрат с выключенным THC и заранее
проверенным физическим зазором; станок удалённо для этого не запускался.

Источники:
https://cdn.vseinstrumenti.ru/instruction/nomenclaturecontent/202006/3224747.pdf/fubag-plasma-40-790396.pdf
https://www.illeon.ru/images/katalog_fubag_2018.pdf
https://www.hypertherm.com/resources/system-support/maintenance-and-use/cut-quality/cut-angularity/

## Главный экран — 2026-10-15

Слева расположены останов/пуск, рабочие координаты, кнопки нуля и программы,
затем регуляторы подачи, быстрых перемещений и ручного джога. В центре —
чертёж и код; высоту этих двух окон можно менять разделителем. Справа —
горелка, THC, датчики, дополнительные режимы и ручные перемещения.

В блоке «ГОРЕЛКА И ДУГА» показаны разные состояния:

- **Разрешить зажигание** — переключатель разрешения Torch Enable.
- **Команда на горелку** — жёлтый индикатор выхода Torch On.
- **Дуга подтверждена** — зелёный индикатор Arc OK; это подтверждение дуги
  от внешнего входа, а не положение переключателя разрешения.

Объекты кнопок и HAL-индикаторов сохранены; меняется их расположение и подписи.
Пустые пользовательские кнопки скрыты. Включение компоновки задаётся параметром
`Workshop main layout = True` в GUI_OPTIONS физического контроллера.

## Отключение THC во время реза

Галка **THC → ENABLE** разрешает только коррекцию Z. Если снять её во время
реза, X/Y продолжают маршрут, а Z удерживает текущую высоту. Повторное
включение возвращает коррекцию по входам внешнего THC. **TORCH ON → ENABLE**
отдельно разрешает зажигание; для настоящего реза её включают до CYCLE START.
При выключенном Torch Enable выполняется прогон без зажигания.

Arc OK остаётся необходимым при настоящем резе независимо от галки THC.
«valid arc lost» означает потерю подтверждения дуги, а «no arc detected after
3 start attempts» — отсутствие подтверждения после трёх попыток. Снятие
галки THC не продолжает уже поставленную на паузу программу автоматически.

2026-10-14 на работающем физическом контроллере проверен загруженный чертёж:
при обесточенных двигателях, изолированном выходе зажигания и имитированных
FLOAT/Arc OK/Up/Down галка THC выключалась дважды во время CUT_MODE_2.
С активной командой Up и затем Down высота Z оставалась постоянной, X/Y
продолжали движение; весь JOB завершился за 22,69 с без паузы. Физические
связи и исходные координаты восстановлены, нули/файл сохранены, оставлен
E-stop. Проверка не подтверждает электрический Arc OK от реальной дуги.
Результаты: `../output/linuxcnc/physical/2026-10-14-thc-toggle-verification.json`.

## Operating Mode

Use QtPlasmaC Mode 2.

- Arc OK comes from the plasma source or relay interface into
  `plasmac.arc-ok-in`.
- Torch height correction comes from the external THC physical controller:
  `plasmac.move-up` and `plasmac.move-down`.
- KerfGrid may still disable THC for small holes and problem geometry through
  QtPlasmaC-compatible G-code, but voltage regulation and up/down decisions stay
  in the external controller.

## Current Hardware Assumption

For the first physical controller setup, assume no Ethernet Mesa board is
available. Treat the machine as a parallel-port/software-stepping target unless
new hardware is introduced.

Install the official LinuxCNC PREEMPT-RT image first because it is the current
straightforward fresh-install path, but accept it only if latency is good enough
for software step generation on the real PC. If base-thread latency is not good
enough, switch to the RTAI path for LPT or add Mesa hardware later instead of
tuning around an unsuitable PREEMPT-RT software-stepping setup.

## Required Signal Contract

Minimum plasma signals for this machine family:

- `plasmac.torch-on`: controller output to torch start relay.
- `plasmac.arc-ok-in`: controller input from Arc OK/transfer.
- `plasmac.float-switch` or `plasmac.ohmic-probe`: probing input.
- `plasmac.move-up`: input from external THC up signal.
- `plasmac.move-down`: input from external THC down signal.

Machine safety signals are separate from QtPlasmaC mode selection. The source
had no valid physical E-stop pin, no enabled home/limit inputs and soft limits
disabled. Those facts do not prove that the physical machine has no safety
circuit; its wiring and behavior must be checked. Source motor-enable outputs
are implemented, but remain electrically unverified while disconnected.

## KerfGrid G-code Contract

KerfGrid output for this controller must keep these properties:

- No CAM-generated Z cutting motion by default.
- Metric `G21`, path tolerance, adaptive feed enable, and QtPlasmaC torch
  control with `M3 $0 S1` and `M5 $0`.
- Material strategy is either temporary material comments or fixed material
  selection with `M190 Pn`, `M66 P3 L3 Q...`, and
  `F#<_hal[plasmac.cut-feed-rate]>`.
- Small holes and small shapes may use reduced feed, THC disable/enable, overcut,
  and early torch-off where the generated path supports it.
- Warnings from import, geometry, safe travel, and offset fallback are operator
  warnings; they must not silently disappear from review, simulation, or G-code
  comments.

## Commissioning Steps

Computer preparation completed on 2026-09-11: realtime load/SSD checks, actual
parport HAL, software XYZ motion, reboot/autostart, native KerfGrid job loading
and the complete torch-off OUTLINE cycle passed. LPT was disconnected throughout.
No physical motion, sensor response or relay operation is claimed by these tests.

The 2026-10-10 source/live comparison and the operator's first-start sequence are
recorded below. The operator confirmed the original Fubag Plasma 40 and external
up/down THC are unchanged; both plasma power and the stepper PSU are off.

1. With equipment powered off, reconnect the controller and inspect the wiring.
   Keep the plasma torch-start circuit physically disconnected for initial tests.
2. Verify the physical E-stop chain and motor enables before commanded motion.
   Check probe, Arc OK and external THC up/down input states and polarity.
3. Jog each axis over short distances at low speed; verify direction, measured
   travel per command, actual usable limits and homing/reference procedure.
   In particular, establish the Z reference and stroke before automatic IHS.
4. Test probing and retract at low speed, still without torch ignition. Verify
   the source-derived floating-head offset against measured switch travel.
5. With the plasma source isolated from ignition, verify the torch relay and
   Arc OK/THC signal response. Restore the normal circuit only after these checks.
6. Run a real torch-off OUTLINE with clear travel before the first cut.
7. Run supervised coupons to calibrate feed, kerf, pierce delay, cut height and
   external THC behavior for the installed Fubag Plasma 40 consumables. The
   current starter cut chart is not a measured calibration.

## Current UTM Autostart

The local UTM VM should autologin to Openbox and start QtPlasmaC from
`/home/linuxcnc/.config/openbox/autostart`. The role starts `dunst` before
QtPlasmaC because QtVCP notification handling needs a notification daemon in this
session.

## Ревью Mach3 и физического LinuxCNC — 2026-10-10

Перенос механики и назначений сигналов соответствует сохранённому рабочему
Mach3. Готовность к реальному резу ещё требует проверки координатной базы,
физической цепи останова, датчика листа и режимов прожига на станке.
Удалённо выполнены только чтения и локальные программные проверки. Движение,
HOME, переключение выходов, розжиг, перезапуск LinuxCNC и нагрузочный тест на
физическом ПК в этом ревью не выполнялись.

### Что проверено

- Прочитаны исходные `/Users/user/Documents/plasma/Mach3/Plasma.xml`,
  `macros/plasma/m3.m1s`, `m5.m1s` и дополнительные макросы. Повторная
  extraction точно совпала с `tools/linuxcnc/plasma-machine-source.yml`.
- `source-import.yml` на ПК соответствует репозиторию. Проверены именно
  активный `qtplasmac_s_metric.ini.expanded`, исполняемый parport Tcl и HAL,
  preferences и загруженный материал, а не только шаблоны Ansible.
- 39 проверок INI совпали; нормализованный активный HAL целиком совпал с
  шаблоном для физического профиля. Направления и масштаб подтверждены
  программно; движение механики с линейкой ещё не проверялось.
- Проверки импорта/роли/загрузчика: 97 passed. Полный KerfGrid: 230 passed,
  3 skipped — отключённые опциональные проверки большого местного DXF-корпуса.
  Тесты локальных IPC/HTTP сокетов повторены вне ограничения sandbox.
- KerfGrid уже передал тестовый чертёж через штатный QtPlasmaC-фильтр и
  показал предпросмотр. Загрузка файла не запускает рез.
- Последнее чтение: IDLE, очередь 0, in-position true, скорости stepgen 0,
  torch-on false, все оси unhomed. Программный Machine ON, поэтому Enable
  P1.14/P1.9 активны. При выключенном питании двигателей DRO не является
  измерением физического положения.
- Во время ревью Wi-Fi временно пропадал; связь восстановилась и состояние
  прочитано повторно. Адрес `.68` остаётся закреплён за MAC
  `A0:47:D7:63:57:B6`. Наличие DHCP lease само по себе не доказывает связь.

### Соответствие движения

| Параметр | Рабочий Mach3 | Активный LinuxCNC | Вывод |
| --- | --- | --- | --- |
| Единицы | мм | мм, G21 | Совпадает |
| X/Y шагов на мм | 160 / 160 | 160 / -160 | Масштаб совпадает; минус Y переносит YRev |
| Z шагов на мм | 1000 | 1000 | Совпадает |
| X/Y предел скорости | 7998 мм/мин | 7998 мм/мин в JOINT | Совпадает |
| Z предел скорости | 642 мм/мин | 642 мм/мин в JOINT | Совпадает |
| X/Y ускорение | 1000 мм/с² | 1000 мм/с² в JOINT | Совпадает |
| Z ускорение | 143 мм/с² | 143 мм/с² в JOINT | Совпадает |
| Диапазоны X/Y/Z | 0…1300 / 0…2250 / 0…50 мм | Те же числа | Реальный используемый ход ещё измерить |
| Полярности STEP/DIR | X normal, Y/Z inverted | Те же инверсии | Совпадает с Motor0/1/2, не со старыми дублями |
| Длительность STEP | 5 мкс | parport reset-time 5 мкс | Номинально совпадает; электрически не измерено |
| DIR setup/hold | исходное DirPulse 5 мкс | INI 5 мкс, фактически округлено к 40 мкс | Более длительная выдержка; не точная копия тайминга |
| Ограничения AXIS | другой механизм Mach3 | скорость/ускорение удвоены, OFFSET_AV_RATIO 0.5 | Это резерв под внешние смещения, JOINT не ускорен |
| Клавиши | →/← X, ↑/↓ Y, PgUp/PgDn Z | Те же стандартные клавиши, shortcuts включены | Подтверждено AxisKeys0…5 и обработчиком GUI |

Mach3 `YRev=1` и инверсия `Motor1DirNeg=1` — отдельные настройки: они
перенесены обе. `AxisKeys4=33`, `AxisKeys5=34` подтверждают PgUp/PgDn.
Поле `negative_keyboard` в исходном extractor не используется HAL и не
является основанием для изменения клавиш; раскладку определяют AxisKeys.

В LinuxCNC base period 40 мкс, double-step включён, stepspace=0, reset следует
после write. Номинальный предел 25 кГц; X/Y требуют 21.328 кГц, Z 10.7 кГц.
Фактическая частота, качество фронтов и отсутствие пропущенных шагов ещё
проверяются на механике. Старый алгоритм CV/LookAhead не имеет точного
соответствия: KerfGrid выдаёт G64 P0.1. Компенсация люфта в Mach3 выключена,
подчинённой оси нет; скрытое четвёртое движение не переносилось. Остаточная
секция JOINT_3 в sample INI не активна при JOINTS=3.

### Соответствие LPT

Используется только порт 1 `0x378`. Порт 2 выключен в исходном Mach3.
Старые именованные P2-записи противоречат действующим indexed Input/Motor и
не используются при переносе.

| Сигнал | Пин порта 1 | Активный уровень | Подключение LinuxCNC |
| --- | --- | --- | --- |
| X STEP / DIR | 2 / 3 | normal / normal | stepgen.0 |
| Y STEP / DIR | 4 / 5 | inverted / inverted | stepgen.1, signed scale -160 |
| Z STEP / DIR | 6 / 7 | inverted / inverted | stepgen.2 |
| Enable 1 / 2 | 14 / 9 | высокий | motion.motion-enabled |
| Пуск плазмы | 17 | высокий | plasmac.torch-on; Mach3 Output7 / DoSpinCW |
| Датчик листа | 15 | высокий | db_float → plasmac.float-switch |
| Arc OK | 12 | низкий | db_arc-ok → plasmac.arc-ok-in |
| THC вверх | 10 | низкий | plasmac.move-up |
| THC вниз | 11 | низкий | plasmac.move-down |

На последнем чтении логические Float/Arc OK/Up/Down были false. Это
подтверждает состояние входов, но не срабатывание датчиков: питание
интерфейсной платы и самого THC отдельно не подтверждено. Программная
обратная связь stepgen считает выданные импульсы, энкодеры двигателя отсутствуют.

### Отличия, которые нужно закрыть до реза

1. **Координатная база Z и ручной HOME.** Активны HOME=HOME_OFFSET=0,
   SEARCH/LATCH=0; HOME объявляет текущую точку машинным нулём. В Mach3 soft
   limits были выключены, в LinuxCNC после HOME действуют диапазоны INI.
   Положение «голова сверху» нельзя произвольно назвать Z=0: штатный фильтр
   добавляет начальный подъём примерно к машинному Z45 при MAX_LIMIT=50.
   Нужна повторяемая физическая база, нижний допустимый уровень с запасом на
   float и измеренный верхний предел. Ноль детали G54 не заменяет эту базу.
   Число 50 из Mach3 с выключенными soft limits не доказывает реальный ход.
2. **Физический останов не виден LinuxCNC.** Старый Input25 указывает P0.0;
   `connect_estop=false`, emc-enable-in замкнут на user-enable-out. Home/limit
   inputs тоже не подключены, как и в исходном профиле. Внешняя аппаратная
   цепь может существовать; её работу нужно подтвердить на станке. Кнопка
   GUI сама по себе не доказывает останов при зависшем ПК. Свободный вход
   нельзя назначать аварийным без проверки схемы.
3. **Прожиг изменён.** Старый M3: G31 Z-50 F800, G92 Z-3, G0 Z8,
   DoSpinCW, G4 P2 и P600. DwellinMilli=1: явная суммарная задержка 0.602 с;
   отдельно в XML есть Spindle Delay CW 1, влияние этой настройки на старый
   DoSpinCW без запущенного Mach3 не подтверждено. Текущий тестовый материал:
   pierce height 3 мм, pierce delay в HAL 0.3 с, cut height 1.5 мм.
   KerfGrid послал pd=0.35; у установленного поля Pierce Delay один знак
   после запятой и шаг 0.1 с, в HAL реально принято 0.3 с. Старый M3 не
   задаёт отдельный переход к cut height 1.5 мм.
   Эти режимы не следует объявлять проверенным переносом старого реза.
4. **THC стал медленнее.** Старый THCSpeed=20% от Z642 = 128.4 мм/мин.
   Сейчас Mode2, thc-feed-rate=642, PID-P=10: по исходнику компонента 1.238
   скорость коррекции = 64.2 мм/мин. Для эквивалента старой скорости нужен
   Speed/PID-P=20 при неизменной Z-скорости. Настройку ещё не меняли.
   Уставка напряжения и чувствительность остаются на внешнем THC; Cut Volts
   103 в CAM не программирует этот прибор. Anti-dive по скорости включён,
   порог 90%. В CUT_MODE_2 версии 1.238 таймер THC Delay не проверяется:
   нельзя рассчитывать на записанные 0.5 с как на задержку его команд.
5. **Поиск листа пока слишком быстрый для первой проверки.** Макрос Mach3
   просил F800, но сохранённый Z-предел 642 ниже. QtPlasmaC сейчас probe/setup
   642, Float Travel 3, Probe Start Height 25. Последние 25 мм считаются от
   Z MIN_LIMIT, а не от поверхности листа. Старая компенсация G92 Z-3 даёт
   стартовую оценку, но QtPlasmaC определяет контакт иначе, с обратным ходом.
   При V=10.7 мм/с и A=143 расчётный тормозной путь ≈0.40 мм плюс ≈0.054 мм
   за debounce 5 мс; реальный запас подвеса надо проверить. Для первого
   Probe Test предложено 100 мм/мин, затем измерить зазор и откалибровать
   Float Travel; это рекомендация для этапа пусконаладки, не применённая настройка.
6. **Материалы не являются старой подтверждённой таблицей.** Тест KerfGrid
   — starter для стали 3 мм/сопла 0.9: 35 A, F1300, kerf 1.2 мм.
   В старых OEMDRO есть несколько групп, например 3 мм/F3200/45 A, но
   назначение групп и field_2 не подтверждено. Их нельзя автоматически
   объявлять рабочей таблицей Fubag 40. Material 0 на ПК — sample с 45 A.
   Fubag и внешний THC не управляются по RS485: ток и напряжение выставляются
   на приборах. Толщина первого образца пользователем пока не указана.

Для первого повторения прежнего процесса стоит согласовать измеренную высоту
прожига со старой командой Z8 и явную задержку около 0.6 с, затем проверить их
на небольшом образце. Не заменять их автоматически starter-оценками.
Первый простой рез выполнить с THC выключенным; после проверки высоты и
стабильной дуги проверить внешний THC отдельно и вернуть его прежнюю скорость.

### Что можно проверить при выключенной силовой части

Можно читать INI/HAL, сверять назначения и состояния входов, загружать чертежи,
смотреть предпросмотр и симуляцию, проверять G-code и локальные тесты CAM.
При отдельно запитанной интерфейсной плате можно вручную сработать float и
наблюдать изменение входа 15 и индикатора; ожидается false → true → false.
Останов/Arc OK/THC проверяются штатными органами и тестовым режимом их
интерфейса, если он предусмотрен; замыкания неизвестных контактов не предлагаются.

Jog/HOME/цикл при выключенных двигателях изменяют только расчётное положение:
они не доказывают масштаб, направление, ход и способность механики остановиться.
Полное отсутствие питания также не позволяет доказать работу контактов/реле.
Горелка и моторы в ходе ревью не включались.

Realtime: nosmt/isolcpus=1/irqaffinity=0 и performance governor действуют;
RT-потоки FIFO98/97 на CPU1, USB/Radeon и остальные IRQ на CPU0. Это совпадает
с принятой подготовкой. Последний законченный нагрузочный замер от 2026-09-11
дал base/servo jitter 12.271/20.780 мкс. После добавления Wi-Fi эквивалентный
законченный замер ещё нужен, при остановленном LinuxCNC и изолированной силовой
части; не запускать одновременно latency-test и действующий HAL. tmax в HAL —
длительность исполнения в CPU clocks, не новый замер джиттера и не наносекунды.

### Порядок первого включения и реза

1. **До подачи питания двигателям:** сохранить текущую конфигурацию, убрать
   программу из режима запуска, Machine OFF/аппаратный останов. Пуск плазмы
   оставить физически изолированным. Проверить Machine OFF перед включением
   PSU. Проверить цепь останова и
   датчик листа при питании только управления, убедиться в правильных индикаторах.
2. **Только двигатели, плазморез ещё выключен:** сначала питание при активном
   останове/Machine OFF, затем осознанно разрешить приводы. Короткие jog на
   0,1–1 мм в пошаговом режиме, без Shift. Проверить знаки,
   прекращение движения при отпускании клавиши, кнопку аппаратного останова.
   После этого измерить X/Y на доступном участке 100 мм и Z на 10 мм,
   возвращение в исходную точку. Не проверять максимальный ход сразу.
3. **Выбрать начало на листе:** ручным джогом установить X/Y и исходную высоту
   над листом, проверить 10 мм запаса вверх, нажать HOME ALL и Ноль XYZ.
   HOME выполняется в этой выбранной точке без поиска концевиков и без движения.
   FLOAT используется только при последующем поиске поверхности. После
   выключения приводов/потери шагов выбранную точку и ноль устанавливать заново.
4. **Проверить поиск листа без дуги:** Probe Test на восстановленной скорости
   Z642 мм/мин после ручной
   проверки датчика; под головой образец, путь свободен. Измерить фактический
   зазор в удержании на pierce height, поправить Float Travel и повторить.
   Проверить выбранные probe start/safe/pierce/cut heights в реальном Z-ходе.
5. **Проверить маршрут без плазмы:** рабочий ноль X/Y на листе, Torch Enable
   выключен и пуск физически изолирован. FRAME сейчас идёт на текущем Z
   (`usecurrentzheight F1000`), поэтому сначала вручную обеспечить зазор.
   Текущий OUTLINE идёт F3000 и содержит M5; в тесте он обходит только наружный
   круг, без внутреннего отверстия. Обычный фильтр добавляет начальный подъём
   Z; это уже реальное автоматическое движение и требует правильной базы.
   Для проверки всего маршрута затем прогнать JOB с выключенным Torch Enable
   и физически изолированным пуском. JOB с M3 выполняет поиск листа и движения
   Z, включая начальный подъём фильтра; выключенный Torch Enable запрещает
   пуск плазмы, но не отменяет IHS. Поэтому этот прогон допустим только после
   проверки направления/базы Z и отдельного Probe Test. Дугу он не проверяет.
   Для первой обводки уменьшить скорость; после неё вернуть feed override на
   100% перед резом. Проверить границы листа, зажимы и полный путь.
6. **Проверить управление источником:** с изолированным розжигом убедиться, что
   реле пуска выключено при старте/останове и работает по команде; подтвердить
   Arc OK и вверх/вниз по штатной процедуре интерфейса. До реза должны быть
   понятны также потеря Arc OK и действие аппаратного останова. Электрическую
   схему и напряжения этого конкретного интерфейса удалённо не проверяли.
7. **Первый короткий рез:** проверить воздух, расходники, рабочий контакт,
   удаление дыма и обычную защиту оператора; поставить прежние проверенные
   ток/настройки источника для выбранного листа. Взять простой короткий прямой
   контур/образец, THC выключить, запуск с начала программы. Проверить высоты,
   прожиг, устойчивый Arc OK и останов. В текущем профиле разрешены 3 попытки
   розжига; для первого диагностического реза разумно ограничить одной попыткой.
8. **THC и качество:** после устойчивого простого реза включить внешний THC,
   подтвердить вверх/вниз и скорость коррекции; сохранить его прежнюю
   чувствительность. Затем купон с квадратом/отверстием: измерить размеры,
   скорректировать kerf/feed/delay и сохранить measured-строку отдельно по
   толщине и установленным расходникам. Большую деталь запускать после этого.

### Данные и первичные источники

- `output/linuxcnc/physical/2026-10-10-mach3-review-snapshot.json` — активные
  INI/HAL/preferences и состояние; `2026-10-10-mach3-review-extra.json` —
  дополнительное чтение THC, потоков и G-code.
- `2026-10-10-mach3-filter-review.json` — фактически загруженный filtered
  G-code с подъёмом G53 Z45 и точность поля Pierce Delay установленного GUI.
- `output/linuxcnc/physical/2026-10-10-mach3-source-review.json` — extraction
  и SHA256 оригиналов; `2026-10-10-mach3-comparison.json` — результат сравнений.
- [QtPlasmaC 2.9: настройка и Probe Test](https://linuxcnc.org/docs/2.9/html/plasma/qtplasmac.html#_initial_setup).
- [LinuxCNC: ручной HOME и система машинных координат](https://linuxcnc.org/docs/2.9/html/config/ini-homing.html).
- [Parallel port: DoubleStep](https://linuxcnc.org/docs/2.9/html/hal/parallel-port.html#_using_doublestep).
- [Mach3 Install/Config, 5.5.2.1 и Appendix A](https://www.machsupport.com/wp-content/uploads/2013/02/Mach3Mill_Install_Config.pdf).
- [Исходник PlasmaC 1.238: скорость и CUT_MODE_2](https://raw.githubusercontent.com/LinuxCNC/linuxcnc/2.9/src/hal/components/plasmac.comp).
- [RTAPI: CPU clocks](https://linuxcnc.org/docs/2.9/html/man/man3/rtapi_get_clocks.3rtapi.html).

Источники проверены 2026-10-10. Программное совпадение не заменяет перечисленные
испытания датчиков, механики и реального реза.
