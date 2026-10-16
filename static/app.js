const $ = (selector) => document.querySelector(selector);
const escapeHTML = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const today = new Date();
const localISO = new Date(today.getTime() - today.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
$('#departure').min = localISO;
$('#departure').value = new Date(today.getTime() - today.getTimezoneOffset() * 60000 + 7 * 86400000).toISOString().slice(0, 10);
$('#return-date').min = $('#departure').value;
$('#departure').addEventListener('change', () => {
  $('#return-date').min = $('#departure').value;
  if ($('#return-date').value && $('#return-date').value <= $('#departure').value) $('#return-date').value = '';
});
$('#swap').addEventListener('click', () => { const a = $('#origin'), b = $('#destination'); [a.value, b.value] = [b.value, a.value]; });
$('#year').textContent = new Date().getFullYear();
const dealTypes = {MNL:'homecoming',CEB:'nature',CRK:'homecoming',KLO:'nature',IST:'city',TBS:'nature'};
function money(price, currency = 'AED') {
  try { return new Intl.NumberFormat('en-AE', {style:'currency', currency, maximumFractionDigits:0}).format(price); }
  catch { return `${escapeHTML(currency)} ${escapeHTML(price)}`; }
}
function searchParams(origin, destination, departure = '', returnDate = '', adults = '1') {
  const params = new URLSearchParams({origin, destination, adults});
  if (departure) params.set('departure', departure);
  if (returnDate) params.set('return', returnDate);
  return params.toString();
}
function renderDeals(deals, filter = 'all') {
  const grid = $('#deal-grid');
  const shown = deals.filter(d => filter === 'all' || (d.category || dealTypes[d.code]) === filter);
  grid.innerHTML = shown.map((d, i) => {
    const partnerHref = `/go/search?${searchParams(d.origin || $('#origin').value || 'AUH', d.code)}`;
    const cta = d.partnerConfigured
      ? `<a class="deal-link" href="${partnerHref}">Check partner fares <span>↗</span></a>`
      : `<a class="deal-link" href="#search" data-dest="${escapeHTML(d.code)}" data-origin="${escapeHTML(d.origin || 'AUH')}">Check route <span>↗</span></a>`;
    return `<article class="deal-card"><div class="deal-visual" style="background:${['#dce5d5','#e5d9ca','#c8e0e0','#e8d7bf','#d6d6e8','#d4e4ce'][i % 6]}"><span class="deal-number">TAKEOFF PICK / ${String(i + 1).padStart(2, '0')}</span><span class="deal-tag">${escapeHTML(d.tag)}</span><span class="emoji">${escapeHTML(d.emoji)}</span></div><div class="deal-body"><div class="deal-title-row"><div><div class="deal-title">${escapeHTML(d.destination)}</div><div class="deal-code">SUGGESTED ROUTE · ${escapeHTML(d.origin || 'AUH')} → ${escapeHTML(d.code)}</div></div>
    <div class="deal-price">${money(d.price, d.currency)}<small> / ${escapeHTML(d.priceLabel || 'sample')}</small></div>
    </div><p class="deal-note">${escapeHTML(d.note)}</p><div class="deal-bottom"><span class="deal-days">✈ ${escapeHTML(d.days)}</span>${cta}</div></div></article>`;
  }).join('') || '<p>No picks in this category yet.</p>';
  grid.querySelectorAll('[data-dest]').forEach(a => a.addEventListener('click', () => {
    $('#destination').value = a.dataset.dest;
    $('#origin').value = a.dataset.origin || 'AUH';
    window.setTimeout(() => $('#destination').focus(), 100);
  }));
}
let deals = [];
fetch('/api/deals').then(async r => { if (!r.ok) throw new Error('Could not load deals'); return r.json(); })
  .then(data => { deals = data.deals || []; renderDeals(deals); })
  .catch(() => { $('#deal-grid').innerHTML = '<p>Could not load destination inspiration. Please refresh the page.</p>'; });
document.querySelectorAll('.filter').forEach(btn => btn.addEventListener('click', () => {
  document.querySelectorAll('.filter').forEach(b => b.classList.toggle('active', b === btn));
  renderDeals(deals, btn.dataset.filter);
}));
$('#flight-search').addEventListener('submit', async (event) => {
  event.preventDefault();
  const status = $('#search-status'), results = $('#search-results');
  status.className = 'search-status'; status.textContent = 'Searching available fares…'; results.innerHTML = '';
  const origin = $('#origin').value.trim().toUpperCase(), destination = $('#destination').value.trim().toUpperCase();
  const departure = $('#departure').value, returnDate = $('#return-date').value, adults = $('#adults').value;
  const params = new URLSearchParams({origin, destination, departure, adults});
  if (returnDate) params.set('return', returnDate);
  try {
    const response = await fetch('/api/search?' + params.toString());
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Search failed');
    status.className = 'search-status success'; status.textContent = `${data.results.length} itinerary option(s). ${data.notice || ''}`;
    if (!data.results.length) { results.innerHTML = '<div class="result-card">No fares found for these dates. Try another date or destination.</div>'; return; }
    results.innerHTML = data.results.map(f => {
      const bookingLink = `/go/search?${searchParams(origin, destination, departure, returnDate, adults)}`;
      const cta = f.bookingUrl ? `<a class="deal-link" href="${escapeHTML(bookingLink)}" target="_blank" rel="sponsored nofollow noopener">Compare & book ↗</a>` : '';
      const departureText = f.departure ? new Date(f.departure).toLocaleString() : 'Departure time unavailable';
      return `<div class="result-card"><div><div class="result-route">${escapeHTML(f.origin)} <span>→</span> ${escapeHTML(f.destination)}</div><div class="result-meta">${escapeHTML(departureText)} · ${f.stops === 0 ? 'Nonstop' : `${escapeHTML(f.stops)} stop(s)`} · ${escapeHTML(f.duration || 'Duration unavailable')}</div></div><div class="result-price">${money(f.price, f.currency)} <small>per traveller*</small>${cta}</div></div>`;
    }).join('');
    if (!data.results.some(f => f.bookingUrl)) {
      results.insertAdjacentHTML('beforeend', '<p class="search-disclaimer">Prices are search results, not a booking. Connect an approved affiliate partner to enable tracked booking links.</p>');
    }
  } catch (error) { status.className = 'search-status error'; status.textContent = error.message; }
});
$('#newsletter-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const status = $('#newsletter-status');
  status.textContent = 'Saving your signup…';
  try {
    const response = await fetch('/api/newsletter', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({email: $('#email').value, consent: $('#newsletter-consent').checked})
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Signup failed.');
    status.textContent = data.message;
    $('#email').value = '';
    $('#newsletter-consent').checked = false;
  } catch (error) { status.textContent = error.message; }
});
$('.menu-toggle').addEventListener('click', () => {
  const links = $('.nav-links'), open = links.classList.toggle('mobile-open');
  $('.menu-toggle').setAttribute('aria-expanded', String(open));
});
