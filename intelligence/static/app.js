const tg = window.Telegram?.WebApp;
const startupTicket = new URLSearchParams(location.search).get('ticket');
const demo = !startupTicket && !tg?.initData && (['localhost','127.0.0.1'].includes(location.hostname) || new URLSearchParams(location.search).has('preview'));
if (demo) document.addEventListener('DOMContentLoaded', () => { document.querySelector('.live-pill').innerHTML = '<span></span> Демо интерфейса'; });
if (tg) {
  tg.ready();
  tg.expand();
  tg.setHeaderColor?.('#0b111b');
  tg.setBackgroundColor?.('#0b111b');
}

const $ = (selector) => document.querySelector(selector);
const escapeHTML = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const money = (value) => value == null ? '—' : `${Number(value).toLocaleString('ru-RU')} ₽`;
const day = (value) => value ? new Date(value).toLocaleDateString('ru-RU', {day:'numeric', month:'short'}) : '—';
const statusName = {active:'Активен',scanning:'Сбор данных',paused:'На паузе',source_unavailable:'Источник недоступен'};
const iconPaths = {
  home:'<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  watch:'<circle cx="11" cy="11" r="7"/><path d="m16.5 16.5 4 4M11 7v4l3 2"/>',
  catalog:'<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M9 10v10"/>',
  star:'<path d="m12 3 2.8 5.8 6.4.9-4.6 4.5 1.1 6.3L12 17.5l-5.7 3 1.1-6.3-4.6-4.5 6.4-.9z"/>',
  chart:'<path d="M4 19V5M4 19h17M8 15l4-5 3 2 5-7"/>',
  phone:'<rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/>',
  laptop:'<rect x="4" y="4" width="16" height="12" rx="1.5"/><path d="M2 20h20l-2-4H4z"/>',
  camera:'<path d="M4 7h4l2-2h4l2 2h4v12H4z"/><circle cx="12" cy="13" r="3"/>',
  chair:'<path d="M6 3v9h12V3M5 12h14v5H5zM7 17v4m10-4v4"/>',
  box:'<path d="m3 7 9-4 9 4v10l-9 4-9-4zM3 7l9 4 9-4m-9 4v10"/>',
  flame:'<path d="M12 22c4.4 0 7-3 7-7 0-3-1.5-5.3-4-7-.1 2-1 3.4-2 4-1-3.3-1.1-6-2-10-3 2.4-6 6.6-6 11 0 5 2.7 9 7 9Z"/>',
  arrow:'<path d="M5 12h14m-6-6 6 6-6 6"/>',
};
const icon = (name) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${iconPaths[name] || iconPaths.catalog}</svg>`;
const productKind = (title) => /macbook|ноутбук|laptop/i.test(title) ? 'laptop' : /sony|canon|nikon|камера|фотоаппарат/i.test(title) ? 'camera' : /диван|стол|шкаф|кресло|мебель/i.test(title) ? 'chair' : /iphone|телефон|смартфон|samsung galaxy/i.test(title) ? 'phone' : 'box';
const safeAvito = (url) => { try { const value = new URL(url); return value.protocol === 'https:' && ['avito.ru','www.avito.ru'].includes(value.hostname) ? value.href : ''; } catch { return ''; } };
const clone = (value) => JSON.parse(JSON.stringify(value));

const demoStore = {
  searches: [
    {id:1,title:'iPhone 15 Pro, 256 ГБ',city:'Москва',status:'active',filters_text:'Цена до 90 000 ₽ · Частные продавцы',target_model:'iPhone 15 Pro',target_memory:'256 ГБ',min_price:null,max_price:90000,seller_filter:'private',condition_filter:'all',notification_mode:'below_market',discount_percent:15,max_alert_price:null,min_score:70,events_mode:'new_and_price',interval_seconds:900,total:128,deals:12,excluded:8,market:{median:80500,low:74900,high:89900,count:64,confidence:'high'},scan_complete:true,last_success:new Date().toISOString(),next_run:new Date().toISOString(),url:'https://www.avito.ru/moskva/telefony?q=iphone+15+pro'},
    {id:2,title:'MacBook Air M3',city:'Москва',status:'active',filters_text:'До 110 000 ₽',target_model:'MacBook Air M3',target_memory:'',min_price:null,max_price:110000,seller_filter:'all',condition_filter:'all',notification_mode:'below_market',discount_percent:15,max_alert_price:null,min_score:70,events_mode:'new_and_price',interval_seconds:900,total:86,deals:7,excluded:4,market:{median:102000,low:93000,high:112000,count:42,confidence:'high'},scan_complete:true,last_success:new Date().toISOString(),next_run:new Date().toISOString(),url:'https://www.avito.ru/moskva/noutbuki?q=macbook+air+m3'},
    {id:3,title:'Sony A7 IV',city:'Санкт-Петербург',status:'paused',filters_text:'Фото и видеокамеры',target_model:'Sony A7 IV',target_memory:'',min_price:null,max_price:null,seller_filter:'all',condition_filter:'all',notification_mode:'below_market',discount_percent:15,max_alert_price:null,min_score:70,events_mode:'new_and_price',interval_seconds:900,total:43,deals:3,excluded:2,market:{median:145000,low:132000,high:160000,count:21,confidence:'medium'},scan_complete:true,last_success:new Date(Date.now()-86400000).toISOString(),next_run:null,url:'https://www.avito.ru/sankt-peterburg/fototehnika?q=sony+a7+iv'},
  ],
  listings: [
    {id:'101',search_id:1,title:'iPhone 15 Pro 256 ГБ, титан',price:68900,market_price:80500,score:92,risk:9,seller_label:'Частное лицо',url:'https://www.avito.ru/',description:'Отличное состояние, полный комплект. Коробка и чек.',reasons:['Цена ниже рынка','Хорошее состояние'],first_seen:new Date().toISOString(),last_seen:new Date().toISOString(),creation_verdict:'new',history:[{price:72900,at:new Date(Date.now()-86400000).toISOString()},{price:68900,at:new Date().toISOString()}]},
    {id:'102',search_id:1,title:'iPhone 15 Pro 256 ГБ, синий',price:73500,market_price:80500,score:88,risk:12,seller_label:'Частное лицо',url:'https://www.avito.ru/',description:'Без сколов, батарея 95%.',reasons:['Цена ниже рынка'],first_seen:new Date().toISOString(),last_seen:new Date().toISOString(),creation_verdict:'new',history:[{price:73500,at:new Date().toISOString()}]},
    {id:'103',search_id:2,title:'MacBook Air M3 16/512',price:89900,market_price:102000,score:91,risk:8,seller_label:'Частное лицо',url:'https://www.avito.ru/',description:'Почти новый ноутбук.',reasons:['Цена ниже рынка','Низкий риск'],first_seen:new Date().toISOString(),last_seen:new Date().toISOString(),creation_verdict:'unverified',history:[{price:89900,at:new Date().toISOString()}]},
    {id:'104',search_id:2,title:'MacBook Air M3, 13 дюймов',price:96000,market_price:102000,score:83,risk:17,seller_label:'Магазин',url:'https://www.avito.ru/',description:'В хорошем состоянии.',reasons:['Цена ниже рынка'],first_seen:new Date().toISOString(),last_seen:new Date().toISOString(),creation_verdict:'new',history:[{price:96000,at:new Date().toISOString()}]},
    {id:'105',search_id:3,title:'Sony A7 IV body',price:134000,market_price:145000,score:85,risk:14,seller_label:'Частное лицо',url:'https://www.avito.ru/',description:'Камера в полном комплекте.',reasons:['Цена ниже рынка'],first_seen:new Date().toISOString(),last_seen:new Date().toISOString(),creation_verdict:'new',history:[{price:134000,at:new Date().toISOString()}]},
  ],
  favorites: ['101','103'],
};

let state = {screen:'home', searchId:null, catalogSearchId:null, q:'', sort:'recent', page:0, dashboard:null, search:null, listings:null, favorites:null, loading:false};
let renderVersion = 0;

async function api(path, options={}) {
  if (demo) return demoApi(path, options);
  const response = await fetch(path, {
    ...options,
    headers: {'X-Telegram-Init-Data':tg?.initData || '','Content-Type':'application/json',...(options.headers || {})},
    cache:'no-store',
  });
  if (!response.ok) {
    let detail = `Ошибка ${response.status}`;
    try { const payload = await response.json(); detail = typeof payload.detail === 'string' ? payload.detail : detail; } catch {}
    const error = new Error(detail); error.status = response.status; throw error;
  }
  return response.status === 204 ? null : response.json();
}

async function demoApi(path, options) {
  await new Promise((resolve) => setTimeout(resolve, 120));
  const url = new URL(path, location.origin);
  const bits = url.pathname.split('/').filter(Boolean);
  const body = options.body ? JSON.parse(options.body) : {};
  if (bits[1] === 'dashboard') return clone({searches:demoStore.searches,recent:demoStore.listings.slice(0,8)});
  if (bits[1] === 'favorites') return clone(demoStore.listings.filter((item) => demoStore.favorites.includes(item.id)));
  if (bits[1] === 'listings') {
    const item = demoStore.listings.find((row) => row.id === bits[2]);
    if (bits[3] === 'favorite') { demoStore.favorites = body.interested ? [...new Set([...demoStore.favorites,bits[2]])] : demoStore.favorites.filter((id) => id !== bits[2]); return {interested:body.interested}; }
    return clone(item);
  }
  if (bits[1] === 'searches') {
    if (bits.length === 2 && options.method === 'POST') {
      const created = {...demoStore.searches[0],...body,id:Date.now(),title:body.title || 'Новый мониторинг',status:'scanning',total:0,deals:0,excluded:0,market:null};
      demoStore.searches.unshift(created); return clone(created);
    }
    const search = demoStore.searches.find((item) => item.id === Number(bits[2]));
    if (!search) throw new Error('Мониторинг не найден');
    if (bits[3] === 'listings') {
      let rows = demoStore.listings.filter((item) => item.search_id === search.id);
      if (url.searchParams.get('q')) rows = rows.filter((item) => item.title.toLowerCase().includes(url.searchParams.get('q').toLowerCase()));
      if (url.searchParams.get('sort') === 'cheap') rows.sort((a,b) => a.price-b.price);
      if (url.searchParams.get('sort') === 'deals') rows = rows.filter((item) => item.price < item.market_price).sort((a,b) => b.score-a.score);
      const page = Number(url.searchParams.get('page') || 0); return clone({items:rows.slice(page*12,(page+1)*12),total:rows.length,page});
    }
    if (bits[3] === 'status') { search.status = body.status; return clone(search); }
    if (bits[3] === 'filter') { search[body.key] = body.value; return clone(search); }
    if (bits[3] === 'scan') return {queued:true};
    if (options.method === 'DELETE') { demoStore.searches = demoStore.searches.filter((item) => item.id !== search.id); return null; }
    return clone(search);
  }
  throw new Error('Недоступно в демо');
}

function toast(message, error=false) {
  const root = $('#toast-root');
  root.innerHTML = `<div class="toast ${error?'error':''}">${escapeHTML(message)}</div>`;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { root.innerHTML = ''; }, 3800);
}
function statusBadge(search) { return `<span class="status ${escapeHTML(search.status)}">${escapeHTML(statusName[search.status] || search.status)}</span>`; }
function nav() {
  const count = state.dashboard?.searches?.length || 0;
  const primary = [['home','Главная','home'],['watch','Мониторинги','watch'],['market','Анализ','chart'],['deals','Предложения','flame']];
  const secondary = [['catalog','Все объявления','catalog'],['star','Избранное','star']];
  const navButton = ([key,title,ic]) => `<button class="nav-item ${state.screen===key || state.screen==='search'&&key==='watch'?'active':''}" data-action="navigate" data-screen="${key}">${icon(ic)}<span>${title}</span>${key==='watch'?`<span class="nav-count">${count}</span>`:''}</button>`;
  $('#desktop-nav').innerHTML = primary.map(navButton).join('') + '<div class="nav-caption nav-caption-secondary">БИБЛИОТЕКА</div>' + secondary.map(navButton).join('');
  $('#mobile-nav').innerHTML = primary.map(([key,title,ic]) => `<button class="${state.screen===key || state.screen==='search'&&key==='watch'?'active':''}" data-action="navigate" data-screen="${key}">${icon(ic)}<span>${title}</span></button>`).join('');
  $('#breadcrumb').innerHTML = `Обзор <span>/</span> ${escapeHTML(({home:'Главная',watch:'Мониторинги',market:'Анализ рынка',deals:'Лучшие предложения',catalog:'Объявления',star:'Избранное',search:state.search?.title || 'Мониторинг'})[state.screen])}`;
}
function demoBanner() { return demo ? '<div class="demo-banner">Режим просмотра: откройте Mini App из Telegram, чтобы увидеть свои данные и сохранять изменения.</div>' : ''; }
function authView(message) { return `<div class="section-head"><div><div class="eyebrow">ЛИЧНЫЙ КАБИНЕТ</div><h1>Войдите через бота</h1><p>Telegram не передал данные входа автоматически. Это можно исправить за один шаг.</p></div></div><div class="panel" style="padding:28px;max-width:510px"><div class="empty-icon">✦</div><h2 style="font-size:16px">Ваши данные под защитой</h2><p style="font-size:11px;color:#8390a5;line-height:1.7">Отправьте боту команду <b>/app</b> и нажмите персональную кнопку «Открыть Mini App». После входа ваши мониторинги появятся здесь.</p><button class="primary-button" data-action="open-bot">Перейти к боту ↗</button>${message?`<div class="error-box">${escapeHTML(message)}</div>`:''}</div>`; }
function empty(title, desc, action='') { return `<div class="empty"><div class="empty-icon">◌</div><strong>${escapeHTML(title)}</strong><p>${escapeHTML(desc)}</p>${action}</div>`; }
function metric(label,value,note,theme,ic) { return `<div class="metric"><div class="metric-top"><span>${label}</span><span class="metric-icon ${theme}">${ic}</span></div><strong class="metric-value">${value}</strong><div class="metric-note">${note}</div></div>`; }
function searchCard(search) { return `<article class="search-card" data-action="open-search" data-id="${search.id}"><div class="card-header"><div class="monitor-symbol">${icon('watch')}</div>${statusBadge(search)}</div><h3>${escapeHTML(search.title)}</h3><div class="card-desc">${escapeHTML(search.city || 'Авито')} · ${escapeHTML(search.target_model || search.filters_text || 'Все предложения')}</div><div class="card-stats"><div><span>Объявлений</span><strong>${search.total ?? 0}</strong></div><div><span>Выгодных</span><strong>${search.deals ?? 0}</strong></div><div><span>Медиана</span><strong>${money(search.market?.median)}</strong></div></div><div class="card-footer"><span>Проверено: ${day(search.last_success)}</span><span class="open">Открыть →</span></div></article>`; }
function listingCard(item) { const discount = item.market_price && item.price != null && item.price < item.market_price ? Math.round((1-item.price/item.market_price)*100) : 0; const kind=productKind(item.title); return `<article class="listing-card" data-action="open-listing" data-id="${escapeHTML(item.id)}"><div class="listing-art category-${kind}">${icon(kind)}${discount>0?`<span class="score-badge">−${discount}% от рынка</span>`:''}</div><h3>${escapeHTML(item.title)}</h3><div class="listing-price">${money(item.price)}</div><div class="listing-meta"><span>${escapeHTML(item.seller_label || 'Продавец не указан')}</span><span>${item.score != null?`${item.score}/100`:'Оценка —'}</span></div></article>`; }
function offerRow(item) { return `<div class="offer-row" data-action="open-listing" data-id="${escapeHTML(item.id)}"><div class="offer-thumb">${icon(productKind(item.title))}</div><div class="offer-info"><strong>${escapeHTML(item.title)}</strong><small>${escapeHTML(item.seller_label || 'Объявление Авито')}</small></div><div class="offer-price">${money(item.price)}<small>${item.score ?? '—'} баллов</small></div></div>`; }

function homeView() {
  const searches = state.dashboard.searches;
  const recent = state.dashboard.recent;
  const total = searches.reduce((sum,item) => sum+(item.total || 0),0);
  const deals = searches.reduce((sum,item) => sum+(item.deals || 0),0);
  const active = searches.filter((item) => ['active','scanning'].includes(item.status)).length;
  return `${demoBanner()}<div class="section-head"><div><div class="eyebrow">ВАШ ЛИЧНЫЙ ПОМОЩНИК</div><h1>Добро пожаловать 👋</h1><p>Всё важное о ваших поисках и выгодных предложениях.</p></div><button class="primary-button" data-action="create"><span class="plus">＋</span> Новый поиск</button></div><section class="hero"><div class="hero-copy"><div class="hero-kicker">✦ INTELLIGENCE INSIGHT</div><h2>Хорошие предложения<br>не ждут долго</h2><p>Автоматически следим за рынком, оцениваем цены и помогаем заметить выгодный вариант.</p><button class="hero-link" data-action="navigate" data-screen="catalog">Смотреть объявления ↗</button></div><div class="hero-art"><i class="hero-orb orb-a"></i><i class="hero-orb orb-b"></i><i class="hero-orb orb-c"></i></div></section><div class="metrics">${metric('Активные поиски',active,'Из '+searches.length+' мониторингов','', '◉')}${metric('Объявлений',total,'В вашей базе','purple','▦')}${metric('Выгодных',deals,'Ниже рыночной цены','green','↘')}${metric('Проверено сегодня',recent.length,'Последние результаты','orange','✓')}</div><div class="panel-grid"><section class="panel"><div class="panel-head"><h2>Мои мониторинги</h2><button data-action="navigate" data-screen="watch">Все мониторинги →</button></div><div class="monitor-list">${searches.length?searches.slice(0,4).map((s)=>`<div class="monitor-row" data-action="open-search" data-id="${s.id}"><div class="monitor-symbol">${icon('watch')}</div><div class="monitor-info"><strong>${escapeHTML(s.title)}</strong><small>${escapeHTML(s.city || 'Авито')} · ${s.total || 0} объявлений</small></div><div class="monitor-meta">${statusBadge(s)}<small>${s.deals || 0} выгодных</small></div><span class="row-arrow">›</span></div>`).join(''):empty('Пока нет мониторингов','Добавьте ссылку на поиск Авито, чтобы начать.','<button class="primary-button" data-action="create">Создать поиск</button>')}</div></section><section class="panel"><div class="panel-head"><h2>Свежие предложения</h2><button data-action="navigate" data-screen="catalog">Смотреть все →</button></div><div class="offer-list">${recent.length?recent.slice(0,5).map(offerRow).join(''):empty('Пока нет объявлений','После первого сбора предложения появятся здесь.')}</div></section></div>`;
}
function watchesView() { const rows = state.dashboard.searches; return `${demoBanner()}<div class="section-head"><div><div class="eyebrow">ВАШИ ПОДПИСКИ</div><h1>Мониторинги</h1><p>Управляйте условиями и проверяйте состояние каждого поиска.</p></div><button class="primary-button" data-action="create"><span class="plus">＋</span> Новый поиск</button></div>${rows.length?`<div class="grid-cards">${rows.map(searchCard).join('')}</div>`:empty('Мониторингов пока нет','Добавьте ссылку на выдачу Авито, и бот начнёт собирать предложения.','<button class="primary-button" data-action="create">Создать мониторинг</button>')}`; }
function catalogView() { const searches=state.dashboard.searches; const selected=state.catalogSearchId || searches[0]?.id; const data=state.listings; return `${demoBanner()}<div class="section-head"><div><div class="eyebrow">УМНЫЙ КАТАЛОГ</div><h1>Объявления</h1><p>Находите подходящее быстрее с фильтрами и оценкой рынка.</p></div></div>${searches.length?`<div class="toolbar"><input class="search-input" id="catalog-query" placeholder="Поиск по названию..." value="${escapeHTML(state.q)}" aria-label="Поиск по названию"><select class="select" id="catalog-search" aria-label="Мониторинг">${searches.map((s)=>`<option value="${s.id}" ${s.id===selected?'selected':''}>${escapeHTML(s.title)}</option>`).join('')}</select><select class="select" id="catalog-sort" aria-label="Сортировка"><option value="recent" ${state.sort==='recent'?'selected':''}>Сначала новые</option><option value="cheap" ${state.sort==='cheap'?'selected':''}>Сначала дешёвые</option><option value="deals" ${state.sort==='deals'?'selected':''}>Выгодные</option></select></div>${data?.items?.length?`<div class="listing-grid">${data.items.map(listingCard).join('')}</div>`:empty('Объявлений не найдено','Попробуйте изменить запрос или дождитесь первого сбора.')}${data?.total>12?`<div class="pagination"><button data-action="page" data-page="${state.page-1}" ${state.page===0?'disabled':''}>‹</button><span>Страница ${state.page+1} из ${Math.ceil(data.total/12)}</span><button data-action="page" data-page="${state.page+1}" ${(state.page+1)*12>=data.total?'disabled':''}>›</button></div>`:''}`:empty('Сначала создайте мониторинг','Каталог появится после добавления поисковой ссылки.','<button class="primary-button" data-action="create">Создать мониторинг</button>')}`; }
function marketView() {
  const searches = state.dashboard.searches;
  const selected = searches.find((s) => s.id === state.marketSearchId) || searches[0];
  const market = selected?.market;
  const range = market && market.high > market.low ? market.high - market.low : 0;
  const position = range ? Math.min(100,Math.max(0,(market.median-market.low)/range*100)) : 50;
  return `${demoBanner()}<div class="section-head"><div><div class="eyebrow">АНАЛИТИКА ПО РЕАЛЬНЫМ ОБЪЯВЛЕНИЯМ</div><h1>Анализ рынка</h1><p>Ориентир цены для выбранного мониторинга.</p></div></div>${selected?`<div class="market-layout"><section class="panel market-main"><div class="market-title"><div><div class="eyebrow">ТЕКУЩИЙ СРЕЗ</div><h2>${escapeHTML(selected.title)}</h2></div><select class="select" id="market-search" aria-label="Выбрать мониторинг">${searches.map((s)=>`<option value="${s.id}" ${s.id===selected.id?'selected':''}>${escapeHTML(s.title)}</option>`).join('')}</select></div>${market?`<div class="market-big-label">Медианная цена</div><div class="market-big-number">${money(market.median)}</div><p class="market-explain">По ${market.count} сопоставимым объявлениям · ${escapeHTML(selected.city || 'Авито')}</p><div class="range-chart" aria-label="Диапазон цен от ${money(market.low)} до ${money(market.high)}, медиана ${money(market.median)}"><div class="range-track"><span class="range-marker" style="left:${position}%"></span></div><div class="range-values"><span>${money(market.low)}<small>Нижняя граница</small></span><span>${money(market.high)}<small>Верхняя граница</small></span></div></div><div class="market-note">Показан текущий срез по собранным объявлениям, без динамики за период.</div>`:empty('Пока мало данных','После сбора объявлений здесь появятся медиана и диапазон рыночных цен.')}<button class="secondary-button" data-action="open-search" data-id="${selected.id}">Настроить мониторинг →</button></section><section class="panel market-aside"><h2>Как читать цену</h2><div class="info-line"><span>Ниже медианы</span><strong>Потенциальная выгода</strong></div><div class="info-line"><span>В пределах диапазона</span><strong>Типичная цена</strong></div><div class="info-line"><span>Выше диапазона</span><strong>Сравните условия</strong></div><p>Оценка учитывает доступные объявления. Перед покупкой проверьте состояние товара и продавца.</p><button class="primary-button" data-action="navigate" data-screen="deals">Найти выгодное →</button></section></div>`:empty('Сначала создайте мониторинг','Добавьте ссылку на поиск Авито, чтобы увидеть анализ рынка.','<button class="primary-button" data-action="create">Создать мониторинг</button>')}`;
}
function dealsView() {
  const rows = state.deals || [];
  return `${demoBanner()}<div class="section-head"><div><div class="eyebrow">ЦЕНА НИЖЕ РЫНКА</div><h1>Лучшие предложения</h1><p>Подходящие объявления из ваших мониторингов.</p></div><button class="secondary-button" data-action="navigate" data-screen="star">☆ Избранное</button></div>${rows.length?`<div class="deals-intro"><span>🔥</span><div><strong>${rows.length} выгодных предложений</strong><small>Сортировка по разнице с медианной ценой рынка</small></div></div><div class="listing-grid deals-grid">${rows.map(listingCard).join('')}</div>`:empty('Пока нет выгодных предложений','После проверки поисков здесь появятся объявления с ценой ниже рынка.','<button class="primary-button" data-action="navigate" data-screen="watch">Мои мониторинги</button>')}`;
}
function favoritesView() { const rows=state.favorites || []; return `${demoBanner()}<div class="section-head"><div><div class="eyebrow">ВАШ СПИСОК</div><h1>Избранное</h1><p>Предложения, к которым хочется вернуться.</p></div></div>${rows.length?`<div class="listing-grid">${rows.map(listingCard).join('')}</div>`:empty('Здесь пока пусто','Откройте объявление и нажмите «Сохранить».')}`; }

function searchView() {
  const s = state.search; if (!s) return '';
  const filter = (label,key,value,options) => `<label class="form-field"><span>${label}</span><select name="${key}" data-original="${escapeHTML(value)}">${options.map(([v,t])=>`<option value="${v}" ${String(value)===v?'selected':''}>${t}</option>`).join('')}</select></label>`;
  const input = (label,key,value,type='number') => `<label class="form-field"><span>${label}</span><input name="${key}" type="${type}" value="${escapeHTML(value ?? '')}" data-original="${escapeHTML(value ?? '')}" placeholder="Без ограничения"></label>`;
  return `${demoBanner()}<button class="back-link" data-action="navigate" data-screen="watch">← Все мониторинги</button><div class="detail-top"><div><div class="eyebrow">НАСТРОЙКИ ПОИСКА</div><h1 class="page-title">${escapeHTML(s.title)}</h1><div class="detail-meta">${statusBadge(s)}<span>${escapeHTML(s.city || 'Авито')}</span><span>·</span><span>Последняя проверка ${day(s.last_success)}</span></div></div><div class="button-row"><button class="ghost-button" data-action="scan" data-id="${s.id}">↻ Проверить сейчас</button><button class="${s.status==='paused'?'primary-button':'secondary-button'}" data-action="toggle" data-id="${s.id}">${s.status==='paused'?'▶ Запустить':'⏸ Пауза'}</button></div></div><div class="detail-grid"><section class="panel"><h2>Условия мониторинга</h2><form id="filter-form" class="form-grid">${input('Минимальная цена, ₽','min_price',s.min_price)}${input('Максимальная цена, ₽','max_price',s.max_price)}${filter('Продавец','seller_filter',s.seller_filter,[['all','Все'],['private','Частные'],['no_shops','Без магазинов']])}${filter('Состояние','condition_filter',s.condition_filter,[['all','Любое'],['new','Новое'],['used','Б/у']])}${filter('Режим уведомлений','notification_mode',s.notification_mode,[['all','Все подходящие'],['below_market','Ниже рынка'],['strong','Сильная скидка'],['max_price','Не дороже лимита'],['score','По оценке']])}${filter('События','events_mode',s.events_mode,[['new_and_price','Новые и снижение цены'],['new','Только новые']])}${input('Скидка от рынка, %','discount_percent',s.discount_percent)}${input('Минимальная оценка','min_score',s.min_score)}${input('Лимит уведомления, ₽','max_alert_price',s.max_alert_price)}${input('Интервал проверки, сек','interval_seconds',s.interval_seconds)}<div class="form-field full"><div class="filter-actions"><button type="submit" class="primary-button">Сохранить условия</button><button type="button" class="ghost-button" data-action="delete" data-id="${s.id}">Удалить мониторинг</button></div></div></form>${s.last_error?`<div class="error-box">Источник: ${escapeHTML(s.last_error)}</div>`:''}</section><section class="panel"><h2>Аналитика поиска</h2><div class="info-line"><span>Объявлений в базе</span><strong>${s.total || 0}</strong></div><div class="info-line"><span>Выгодных вариантов</span><strong>${s.deals || 0}</strong></div><div class="info-line"><span>Исключено</span><strong>${s.excluded || 0}</strong></div><div class="info-line"><span>Состояние сбора</span><strong>${s.scan_complete?'Завершён':'Страница '+(s.next_page || 1)}</strong></div><div class="market-block"><small>МЕДИАНА РЫНКА</small><strong>${money(s.market?.median)}</strong><span>${s.market?`Диапазон ${money(s.market.low)} — ${money(s.market.high)} · ${s.market.count} предложений`:'Недостаточно сопоставимых объявлений'}</span></div><div class="filter-actions"><button class="secondary-button" data-action="catalog-for" data-id="${s.id}">Смотреть объявления →</button></div></section></div><div class="subsection"><div class="subsection-head"><h2>Последние объявления</h2><button class="text-link" data-action="catalog-for" data-id="${s.id}">Все объявления →</button></div>${state.listings?.items?.length?`<div class="listing-grid">${state.listings.items.slice(0,3).map(listingCard).join('')}</div>`:empty('Пока нет объявлений','После сбора они появятся здесь.')}</div>`;
}

async function loadDashboard() { state.dashboard = await api('/api/dashboard'); }
async function loadListings(searchId) { state.listings = await api(`/api/searches/${searchId}/listings?q=${encodeURIComponent(state.q)}&sort=${encodeURIComponent(state.sort)}&page=${state.page}`); }
async function render() {
  const version = ++renderVersion;
  $('#content').innerHTML = '<div class="loading"><div><div class="spinner"></div>Загружаем данные...</div></div>';
  try {
    if (!state.dashboard || ['home','watch','catalog','market','deals'].includes(state.screen)) await loadDashboard();
    if (state.screen === 'search') { state.search = await api(`/api/searches/${state.searchId}`); state.listings = await api(`/api/searches/${state.searchId}/listings?page=0`); }
    if (state.screen === 'catalog') { state.catalogSearchId ||= state.dashboard.searches[0]?.id; state.listings = state.catalogSearchId ? await api(`/api/searches/${state.catalogSearchId}/listings?q=${encodeURIComponent(state.q)}&sort=${encodeURIComponent(state.sort)}&page=${state.page}`) : {items:[],total:0,page:0}; }
    if (state.screen === 'deals') { const batches = await Promise.all(state.dashboard.searches.slice(0,10).map((search) => api(`/api/searches/${search.id}/listings?sort=deals&page=0`).then((data) => data.items).catch(() => []))); state.deals = batches.flat().sort((a,b) => ((b.market_price-b.price)/b.market_price)-((a.market_price-a.price)/a.market_price)).slice(0,30); }
    if (state.screen === 'star') state.favorites = await api('/api/favorites');
    if (version !== renderVersion) return;
    nav();
    $('#content').innerHTML = ({home:homeView,watch:watchesView,catalog:catalogView,star:favoritesView,market:marketView,deals:dealsView,search:searchView})[state.screen]();
  } catch (error) { if (version===renderVersion) { $('#content').innerHTML = error.status===401 ? authView(error.message) : empty('Не удалось загрузить данные',error.message,'<button class="primary-button" data-action="refresh">Повторить</button>'); if(error.status!==401) toast(error.message,true); } }
}

function createModal() {
  $('#overlay-root').innerHTML = `<div class="overlay" data-action="dismiss"><div class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title"><div class="modal-head"><div><div class="eyebrow">НОВЫЙ МОНИТОРИНГ</div><h2 id="modal-title">Добавить поиск</h2><p>Вставьте ссылку на страницу выдачи Авито.<br>Параметры поиска возьмём прямо из неё.</p></div><button class="close-button" data-action="close" aria-label="Закрыть">×</button></div><form id="create-form" class="form-grid"><label class="form-field full"><span>Ссылка на поиск Авито *</span><input name="url" type="url" placeholder="https://www.avito.ru/..." required></label><label class="form-field full"><span>Название мониторинга</span><input name="title" placeholder="Например, iPhone 15 Pro"></label><label class="form-field"><span>Модель</span><input name="target_model" placeholder="iPhone 15 Pro"></label><label class="form-field"><span>Память</span><input name="target_memory" placeholder="256 ГБ"></label><div class="form-field full"><div class="modal-actions"><button type="button" class="ghost-button" data-action="close">Отмена</button><button type="submit" class="primary-button">Создать мониторинг</button></div></div></form></div></div>`;
  $('#create-form input')?.focus();
}
async function listingDrawer(id) {
  try {
    const item = await api(`/api/listings/${encodeURIComponent(id)}`);
    const saved = (await api('/api/favorites')).some((row) => row.id === id);
    const url = safeAvito(item.url);
    $('#overlay-root').innerHTML = `<div class="overlay drawer-overlay" data-action="dismiss"><div class="drawer" role="dialog" aria-modal="true" aria-label="Карточка объявления"><div class="modal-head"><div><div class="eyebrow">КАРТОЧКА ОБЪЯВЛЕНИЯ</div><h2>${escapeHTML(item.title)}</h2><p>${escapeHTML(item.seller_label || 'Продавец не указан')} · ${day(item.first_seen)}</p></div><button class="close-button" data-action="close" aria-label="Закрыть">×</button></div><div class="listing-art" style="height:165px">${icon(productKind(item.title))}</div><div class="drawer-price">${money(item.price)}</div><div class="detail-meta">${item.score!=null?`Оценка ${item.score}/100`:'Оценка недоступна'} · Риск ${item.risk ?? '—'}/100</div>${item.market_price?`<div class="market-block"><small>МЕДИАНА РЫНКА</small><strong>${money(item.market_price)}</strong><span>${item.price < item.market_price ? `Ниже рынка на ${Math.round((1-item.price/item.market_price)*100)}%` : 'Цена не ниже рынка'}</span></div>`:''}<div class="drawer-section"><h3>Описание</h3><p>${escapeHTML(item.description || 'Описание не указано.')}</p></div><div class="drawer-section"><h3>Почему это объявление</h3><div class="pill-list">${(item.reasons || []).length?item.reasons.map((reason)=>`<span>${escapeHTML(reason)}</span>`).join(''):'<span>Оценка ещё не рассчитана</span>'}</div></div>${item.history?.length?`<div class="drawer-section"><h3>История цен</h3>${item.history.map((row)=>`<div class="history-row"><span>${day(row.at)}</span><strong>${money(row.price)}</strong></div>`).join('')}</div>`:''}${item.text_summary?`<div class="drawer-section"><h3>Анализ текста</h3><p>${escapeHTML(item.text_summary)}</p></div>`:''}<div class="drawer-actions"><button class="secondary-button" data-action="favorite" data-id="${escapeHTML(id)}" data-interested="${saved?'false':'true'}">${saved?'★ Убрать':'☆ Сохранить'}</button>${url?`<button class="primary-button" data-action="open-avito" data-url="${escapeHTML(url)}">Открыть на Авито ↗</button>`:''}</div></div></div>`;
  } catch (error) { toast(error.message,true); }
}
function closeOverlay() { $('#overlay-root').innerHTML = ''; }
async function action(node, event) {
  const kind = node.dataset.action, id = node.dataset.id;
  if (kind==='close') return closeOverlay();
  if (kind==='dismiss') { if (node === event.target) closeOverlay(); return; }
  if (kind==='create') return createModal();
  if (kind==='open-bot') { const url='https://t.me/avito_intelligence_bot'; if(tg?.openTelegramLink) tg.openTelegramLink(url); else window.open(url,'_blank','noopener'); return; }
  if (kind==='navigate') { state.screen=node.dataset.screen; state.page=0; state.q=''; return render(); }
  if (kind==='open-search') { state.screen='search'; state.searchId=Number(id); return render(); }
  if (kind==='open-listing') return listingDrawer(id);
  if (kind==='catalog-for') { state.catalogSearchId=Number(id); state.screen='catalog'; state.page=0; state.q=''; return render(); }
  if (kind==='page') { state.page=Number(node.dataset.page); return render(); }
  if (kind==='refresh') { state.dashboard=null; return render(); }
  if (kind==='open-avito') { const url=safeAvito(node.dataset.url); if (url) tg?.openLink ? tg.openLink(url) : window.open(url,'_blank','noopener'); return; }
  try {
    if (kind==='toggle') { const s=state.search; await api(`/api/searches/${id}/status`,{method:'PATCH',body:JSON.stringify({status:s.status==='paused'?'active':'paused'})}); toast(s.status==='paused'?'Мониторинг запущен':'Мониторинг приостановлен'); state.dashboard=null; await render(); }
    if (kind==='scan') { await api(`/api/searches/${id}/scan`,{method:'POST'}); toast('Проверка поставлена в очередь'); }
    if (kind==='delete') { if (!confirm('Удалить мониторинг и его настройки?')) return; await api(`/api/searches/${id}`,{method:'DELETE'}); state.screen='watch'; state.dashboard=null; toast('Мониторинг удалён'); await render(); }
    if (kind==='favorite') { const interested=node.dataset.interested==='true'; await api(`/api/listings/${encodeURIComponent(id)}/favorite`,{method:'POST',body:JSON.stringify({interested})}); toast(interested?'Добавлено в избранное':'Удалено из избранного'); node.dataset.interested=String(!interested); node.textContent=interested?'★ Убрать':'☆ Сохранить'; if(state.screen==='star') render(); }
  } catch (error) { toast(error.message,true); }
}
document.addEventListener('click',(event)=>{ const node=event.target.closest('[data-action]'); if (node) action(node,event); });
document.addEventListener('change',(event)=>{ if (event.target.id==='catalog-search') { state.catalogSearchId=Number(event.target.value); state.page=0; render(); } if (event.target.id==='market-search') { state.marketSearchId=Number(event.target.value); render(); } if (event.target.id==='catalog-sort') { state.sort=event.target.value; state.page=0; render(); } });
document.addEventListener('input',(event)=>{ if (event.target.id==='catalog-query') { state.q=event.target.value; state.page=0; clearTimeout(window.searchTimer); window.searchTimer=setTimeout(render,300); } });
document.addEventListener('submit',async(event)=>{
  if (event.target.id==='create-form') {
    event.preventDefault(); const form=event.target; const body=Object.fromEntries(new FormData(form)); const submit=form.querySelector('[type=submit]'); submit.disabled=true; submit.textContent='Проверяем ссылку...';
    try { const search=await api('/api/searches',{method:'POST',body:JSON.stringify(body)}); closeOverlay(); state.dashboard=null; state.screen='search'; state.searchId=search.id; toast('Мониторинг создан'); await render(); } catch(error) { toast(error.message,true); submit.disabled=false; submit.textContent='Создать мониторинг'; }
  }
  if (event.target.id==='filter-form') {
    event.preventDefault(); const form=event.target; const submit=form.querySelector('[type=submit]'); submit.disabled=true;
    try { for (const field of form.querySelectorAll('[name]')) { const value=field.value.trim(); if(value!==field.dataset.original) await api(`/api/searches/${state.searchId}/filter`,{method:'PATCH',body:JSON.stringify({key:field.name,value:value || '-'})}); } state.dashboard=null; toast('Условия сохранены'); await render(); } catch(error) { toast(error.message,true); } finally { submit.disabled=false; }
  }
});
document.addEventListener('keydown',(event)=>{ if(event.key==='Escape') closeOverlay(); });
async function startApp() {
  if (startupTicket) {
    try {
      await api('/api/session',{method:'POST',body:JSON.stringify({ticket:startupTicket})});
      const url=new URL(location.href); url.searchParams.delete('ticket'); history.replaceState({},'',url.pathname+url.search+url.hash);
    } catch(error) { $('#content').innerHTML=authView(error.message); return; }
  }
  render();
}
startApp();
