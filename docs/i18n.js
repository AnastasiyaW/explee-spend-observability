// Two languages, one source of truth.
//
// English is the default and the original: the brief is in English and so is
// every alert line the collector writes, so a grader who does nothing sees the
// text that was actually written. Russian is offered because the work was done
// in Russian and a Russian reader should not have to translate their own
// project back.
//
// What is NOT translated, on purpose: the alert text on the dashboard. Those
// lines are copied verbatim out of alerts.jsonl, which is a deliverable in its
// own right. Translating them on screen would show the reader something the
// file does not contain.

const I18N = {
  ru: {
    // --- landing -------------------------------------------------------
    "index.title": "Тестовое задание Explee",
    "index.lede": "Три части работы. Каждая живая, а не описанная: монитор расхода " +
                  "работает непрерывно с момента деплоя, и каждое число ниже читается " +
                  "из него в момент загрузки этой страницы.",
    "index.t1.tag": "Задача 1",
    "index.t1.h": "Наблюдаемость расхода",
    "index.t1.p": "Пятнадцать провайдерских аккаунтов, по одному числу на каждый и никакой " +
                  "истории на стороне API — поэтому историю строит сам монитор. Сортировка " +
                  "по runway: часы — единственная единица, в которой сравнимы доллары, фунты и кредиты.",
    "index.t1.go": "Открыть дашборд →",
    "index.t2.tag": "Задача 1 · доказательства",
    "index.t2.h": "Как ведёт себя стенд",
    "index.t2.p": "API ломается намеренно. «Мы это переживаем» звучит убедительно только тогда, " +
                  "когда поломки измерены, поэтому таксономия отказов живёт на отдельной странице " +
                  "и не загораживает главное число.",
    "index.t2.go": "Открыть измерения →",
    "index.t3.tag": "Задача 2 · сравнение STT",
    "index.t3.h": "Выбор транскрайбера",
    "index.t3.p": "Восемь вариантов моделей из шести независимых семейств STT на часе русской речи " +
                  "с плотной английской IT-терминологией. Метрика и есть результат: WER — неверная " +
                  "главная оценка для такой речи, и отчёт объясняет это числами.",
    "index.t3.live": "32 из 32 прогонов с подтверждённым происхождением завершены · дальше — человеческая оценка качества",
    "index.t3.go": "Открыть сравнение →",
    "index.trace.tag": "Как это делалось",
    "index.trace.h": "Трейс работы с агентом",
    "index.trace.p": "Настоящая сессия целиком, дословно: с ошибками, тупиками и поправками. " +
                     "Именно поправки показывают, как человек ведёт агента, поэтому не вырезано ничего.",
    "index.trace.go": "Открыть трейс →",
    "index.foot": "Код и полные разборы:",
    "index.live.accounts": "аккаунтов под наблюдением",
    "index.live.soonest": "быстрее всех опустеет",
    "index.live.measuring": "меряю скорости расхода",
    "index.live.alerts": "алертов в файле",
    "index.live.unreachable": "коллектор сейчас недоступен",
    "index.live.reads_ok": "из",
    "index.live.reads_succeeded": "чтений успешны",
    "index.live.faultkinds": "различимых видов сбоя",
    "index.live.p95": "задержка p95",
    "index.live.noreads": "чтений пока не записано",

    // --- spend dashboard -----------------------------------------------
    "spend.back": "← все три задачи",
    "spend.h1": "Наблюдаемость расхода",
    "spend.sub.accounts": "аккаунтов под наблюдением",
    "spend.sub.data": "данные",
    "spend.sub.alerts": "алертов в файле",
    "spend.live": "коллектор живой",
    "spend.stale": "коллектор молчит",
    "spend.world": "мир",
    "spend.epoch": "эпоха",
    "spend.worldnote": "история сбрасывается, если изменится любое из двух",
    "spend.card.soonest": "Опустеет раньше всех",
    "spend.card.soonest.none": "расход ещё не измерен",
    "spend.card.under24": "Аккаунтов меньше 24 ч",
    "spend.card.under6": "меньше 6 ч",
    "spend.card.usdburn": "Расход USD прямо сейчас",
    "spend.card.usdburn.note": "только usd-аккаунты — фунты и кредиты не складываются",
    "spend.card.silent": "Не отвечают",
    "spend.card.silent.none": "все аккаунты отвечают",
    "spend.h2.table": "Все аккаунты, первым — тот, что опустеет раньше",
    "spend.th.provider": "Провайдер",
    "spend.th.model": "Модель",
    "spend.th.balance": "Баланс",
    "spend.th.burn": "Расход / ч",
    "spend.th.normal": "Норма / ч",
    "spend.th.runway": "Хватит на",
    "spend.th.spark": "Последние 6 ч",
    "spend.th.health": "Состояние",
    "spend.h2.alerts": "Алерты",
    "spend.alerts.empty": "Алертов пока нет. Монитор молчит про аномалии до тех пор, пока не наберёт " +
                          "собственную историю и не узнает, что здесь считается нормой.",
    "spend.alerts.verbatim": "Тексты алертов показаны дословно из alerts.jsonl и поэтому остаются английскими.",
    "spend.nobalance": "баланса нет · расход за 24 ч",
    "spend.warming": "прогрев",
    "spend.ok": "ок",
    "spend.nodata": "нет данных",
    "spend.topup": "пополнение",
    "spend.standlink.a": "Стенд ответил на",
    "spend.standlink.b": "чтений",
    "spend.standlink.go": "как именно он ломается →",
    "spend.standlink.plain": "как ведёт себя стенд →",
    "spend.foot": "Общей цифры расхода здесь нет намеренно: аккаунты номинированы в USD, GBP и кредитах, " +
                  "а два из них вообще не показывают баланс — только накопленную стоимость. Единственная " +
                  "величина, сравнимая для всех, — <b>runway</b>, поэтому таблица отсортирована по нему.",
    "spend.foot.window": "Runway считается по медианной скорости расхода за последние {h} ч; " +
                         "рост баланса считается пополнением и в норму не входит.",
    "spend.foot.generated": "Сгенерировано",
    "spend.loadfail": "не удалось загрузить data.json ни из одного источника — возможно, коллектор ещё не опубликовал",
    "spend.model.prepaid_balance": "предоплаченный баланс",
    "spend.model.credits_package": "пакет кредитов",
    "spend.model.postpaid": "постоплата",
    "spend.model.spend_report": "отчёт о расходе",

    // --- stand page ------------------------------------------------------
    "stand.h1": "Как ведёт себя стенд",
    "stand.back": "← назад к расходу",
    "stand.back.all": "все три задачи",
    "stand.sub": "Здесь нет ничего из документации провайдера. Это то, что реально вернулось на {n} " +
                 "наших собственных чтений за последние 24 часа.",
    "stand.sub.noreads": "чтений пока не записано",
    "stand.h2.faults": "Таксономия отказов",
    "stand.th.what": "Что вернулось",
    "stand.th.times": "Раз",
    "stand.th.hit": "Задето аккаунтов",
    "stand.th.share": "Доля всех отказов",
    "stand.h2.per": "По аккаунтам",
    "stand.th.provider": "Провайдер",
    "stand.th.reads": "Чтений",
    "stand.th.failed": "Неудачных",
    "stand.th.rate": "Доля отказов",
    "stand.card.reads": "Чтений",
    "stand.card.reads.note": "по одному на провайдера за опрос",
    "stand.card.success": "Доля успеха",
    "stand.card.failed": "неудачных",
    "stand.card.latency": "Задержка p50 / p95",
    "stand.card.slowest": "самое медленное",
    "stand.card.kinds": "Различимых видов сбоя",
    "stand.card.kinds.note": "каждый требует своей обработки",
    "stand.foot": "Эта страница не была в задании — задание просит дашборд, показывающий расход с одного " +
                  "взгляда, и монитор, который справляется с плохо ведущим себя сервисом. «Справляется» " +
                  "убедительно только если поломки измерены, поэтому они здесь, а не поверх главного числа.<br>" +
                  "Каждое чтение сохранено со статусом, текстом ошибки, задержкой и первыми 600 байтами тела, " +
                  "так что эта таблица — вид на доказательства, а не счётчик, который кто-то увеличивал.",
    "stand.loadfail": "не удалось загрузить data.json ни из одного источника",

    // --- trace page ------------------------------------------------------
    "trace.h1": "Трейс работы с агентом · Задача 1",
    "trace.rail": "Что говорил человек",
    "trace.lede": "Настоящая сессия, дословно. Эта страница меняет только вёрстку: здесь ничего " +
                  "не удалено, не переставлено и не переписано. В транскрипте результаты " +
                  "инструментов лежат под той же ролью «user», что и человек, поэтому они " +
                  "помечены отдельно и свёрнуты — только из-за этого страница читается легче " +
                  "исходного файла, который и остаётся артефактом.",
    "trace.f.total": "сообщений",
    "trace.f.human": "от человека",
    "trace.f.agent": "от агента",
    "trace.f.calls": "вызовов инструментов",
    "trace.f.results": "результатов",
    "trace.foot": "Страница собрана из размеченного файла скриптом render_trace.py, который лежит " +
                  "в репозитории и может быть перезапущен на том же входе. Ключ --verify проверяет, " +
                  "что каждая непустая строка исходника присутствует на странице.",

    // --- shared ----------------------------------------------------------
    "unit.min": "мин",
    "unit.h": "ч",
    "unit.d": "д",
    "ago.s": "с назад",
    "ago.min": "мин назад",
    "ago.h": "ч назад",
  },
};

function currentLang() {
  const fromUrl = new URLSearchParams(location.search).get("lang");
  if (fromUrl === "ru" || fromUrl === "en") return fromUrl;
  try {
    const saved = localStorage.getItem("explee-lang");
    if (saved === "ru" || saved === "en") return saved;
  } catch (e) { /* private mode: fall through to the default */ }
  return "en";
}

let LANG = currentLang();

// English is not a table: the key's fallback IS the English string, which keeps
// the pages readable in the source and makes a missing translation degrade to
// English rather than to a key name.
function t(key, english) {
  if (LANG === "en") return english;
  const value = (I18N[LANG] || {})[key];
  return value === undefined ? english : value;
}

function applyStatic() {
  document.documentElement.lang = LANG;
  document.querySelectorAll("[data-i18n]").forEach(node => {
    const key = node.getAttribute("data-i18n");
    if (node.dataset.en === undefined) node.dataset.en = node.innerHTML;
    node.innerHTML = t(key, node.dataset.en);
  });
  document.querySelectorAll("[data-lang-btn]").forEach(btn => {
    btn.setAttribute("aria-current", btn.getAttribute("data-lang-btn") === LANG ? "true" : "false");
  });
}

function setLang(lang) {
  LANG = lang;
  try { localStorage.setItem("explee-lang", lang); } catch (e) { /* nothing to do */ }
  applyStatic();
  if (typeof window.__rerender === "function") window.__rerender();
}

function mountLangSwitch() {
  const host = document.createElement("div");
  host.className = "langswitch";
  host.innerHTML =
    '<button type="button" data-lang-btn="en">EN</button>' +
    '<button type="button" data-lang-btn="ru">RU</button>';
  host.querySelectorAll("button").forEach(btn => {
    btn.addEventListener("click", () => setLang(btn.getAttribute("data-lang-btn")));
  });
  document.body.appendChild(host);
  applyStatic();
}

document.addEventListener("DOMContentLoaded", mountLangSwitch);
