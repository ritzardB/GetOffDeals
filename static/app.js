/* =========================================================
   GetOffDeals — Main frontend JavaScript
   ========================================================= */

const $ = (selector) => document.querySelector(selector);

const escapeHTML = (value) =>
  String(value ?? '').replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  })[ch]);

/* =========================================================
   1. Date setup and flight form helpers
   ========================================================= */

const today = new Date();

const localISO = new Date(
  today.getTime() - today.getTimezoneOffset() * 60000
).toISOString().slice(0, 10);

const departureInput = $('#departure');
const returnInput = $('#return-date');
const originInput = $('#origin');
const destinationInput = $('#destination');
const flightSearchForm = $('#flight-search');

if (departureInput && returnInput) {
  departureInput.min = localISO;

  departureInput.value = new Date(
    today.getTime() -
    today.getTimezoneOffset() * 60000 +
    7 * 86400000
  ).toISOString().slice(0, 10);

  returnInput.min = departureInput.value;

  departureInput.addEventListener('change', () => {
    returnInput.min = departureInput.value;

    if (
      returnInput.value &&
      returnInput.value <= departureInput.value
    ) {
      returnInput.value = '';
    }
  });
}

$('#swap')?.addEventListener('click', () => {
  if (!originInput || !destinationInput) return;

  const currentOrigin = originInput.value;

  originInput.value = destinationInput.value;
  destinationInput.value = currentOrigin;
});

if ($('#year')) {
  $('#year').textContent = new Date().getFullYear();
}

/* =========================================================
   2. Deal helpers
   ========================================================= */

const dealTypes = {
  MNL: 'homecoming',
  CEB: 'nature',
  CRK: 'homecoming',
  KLO: 'nature',
  IST: 'city',
  TBS: 'nature',
};

const dealColors = [
  '#dce5d5',
  '#e5d9ca',
  '#c8e0e0',
  '#e8d7bf',
  '#d6d6e8',
  '#d4e4ce',
];

function money(price, currency = 'AED') {
  try {
    return new Intl.NumberFormat('en-AE', {
      style: 'currency',
      currency,
      maximumFractionDigits: 0,
    }).format(price);
  } catch {
    return `${escapeHTML(currency)} ${escapeHTML(price)}`;
  }
}

function searchParams(
  origin,
  destination,
  departure = '',
  returnDate = '',
  adults = '1'
) {
  const params = new URLSearchParams({
    origin,
    destination,
    adults,
  });

  if (departure) params.set('departure', departure);
  if (returnDate) params.set('return', returnDate);

  return params.toString();
}

/* =========================================================
   3. Destination selection
   ========================================================= */

/*
 * Select a destination and bring the user to the flight
 * search form. The user must still submit the search.
 *
 * IMPORTANT:
 * - Preserve the origin selected by the user.
 * - Do not automatically submit the flight search.
 * - Do not redirect to an affiliate partner.
 */


function selectDestination(code) {
  const params = new URLSearchParams();

  if (code) params.set('destination', code);

  window.location.href = `/flights?${params.toString()}`;
}

/* =========================================================
   4. Render destination cards
   ========================================================= */

function renderDeals(deals, filter = 'all') {
  const grid = $('#deal-grid');

  if (!grid) return;

  const shown = deals.filter((deal) => {
    return (
      filter === 'all' ||
      (deal.category || dealTypes[deal.code]) === filter
    );
  });

  if (!shown.length) {
    grid.innerHTML =
      '<p class="deal-empty">No picks in this category yet.</p>';
    return;
  }

  grid.innerHTML = shown.map((deal, index) => {
    const code = String(deal.code || '').toUpperCase();
    const dealOrigin = deal.origin || 'AUH';
    const destinationName = deal.destination || code;

    const partnerHref = `/go/search?${searchParams(
      dealOrigin,
      code
    )}`;

    /*
     * Keep the existing affiliate CTA when a partner is
     * configured. Otherwise, the CTA selects the route.
     */
    const cta = deal.partnerConfigured
      ? `
        <a
          class="deal-link"
          href="${escapeHTML(partnerHref)}"
          rel="sponsored nofollow"
        >
          Check partner fares <span>↗</span>
        </a>
      `
      : `
        <a
          class="deal-link"
          href="#search"
          data-dest="${escapeHTML(code)}"
        >
          Check route <span>↗</span>
        </a>
      `;

    return `
      <article
        class="deal-card"
        data-card-dest="${escapeHTML(code)}"
        tabindex="0"
        aria-label="Select ${escapeHTML(destinationName)} as your flight destination"
      >
        <div
          class="deal-visual"
          style="background:${dealColors[index % dealColors.length]}"
        >
          <span class="deal-number">
            TAKEOFF PICK / ${String(index + 1).padStart(2, '0')}
          </span>

          <span class="deal-tag">
            ${escapeHTML(deal.tag || 'DESTINATION')}
          </span>

          <span class="emoji">
            ${escapeHTML(deal.emoji || '✈️')}
          </span>
        </div>

        <div class="deal-body">
          <div class="deal-title-row">
            <div>
              <div class="deal-title">
                ${escapeHTML(destinationName)}
              </div>

              <div class="deal-code">
                SUGGESTED ROUTE ·
                ${escapeHTML(dealOrigin)}
                → ${escapeHTML(code)}
              </div>
            </div>

            <div class="deal-price">
              ${money(deal.price, deal.currency || 'AED')}
              <small>
                / ${escapeHTML(deal.priceLabel || 'sample')}
              </small>
            </div>
          </div>

          <p class="deal-note">
            ${escapeHTML(deal.note || '')}
          </p>

          <div class="deal-bottom">
            <span class="deal-days">
              ✈ ${escapeHTML(deal.days || '')}
            </span>

            ${cta}
          </div>
        </div>
      </article>
    `;
  }).join('');
}

/* =========================================================
   5. Destination card click handling
   ========================================================= */

/*
 * Use event delegation so the handlers continue working
 * whenever renderDeals() rebuilds the cards after filtering.
 *
 * Clicking the card body selects the destination.
 * Clicking an actual link keeps its normal behavior.
 */

const dealGrid = $('#deal-grid');

if (dealGrid) {
  dealGrid.addEventListener('click', (event) => {
    const target = event.target;

    if (!(target instanceof Element)) return;

    // Never intercept affiliate links or other interactive controls.
    if (
      target.closest(
        'a, button, input, select, textarea, label'
      )
    ) {
      return;
    }

    const card = target.closest('[data-card-dest]');

    if (!card || !dealGrid.contains(card)) return;

    selectDestination(card.dataset.cardDest);
  });

  // Make the card body keyboard accessible.
  dealGrid.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' && event.key !== ' ') return;

    const target = event.target;

    if (!(target instanceof Element)) return;

    // Let links and other controls handle their own keys.
    if (
      target.closest(
        'a, button, input, select, textarea, label'
      )
    ) {
      return;
    }

    const card = target.closest('[data-card-dest]');

    if (!card || !dealGrid.contains(card)) return;

    event.preventDefault();
    selectDestination(card.dataset.cardDest);
  });
}

/*
 * The non-partner "Check route" CTA still selects the route.
 * Partner-configured links are not intercepted.
 */
if (dealGrid) {
  dealGrid.addEventListener('click', (event) => {
    const target = event.target;

    if (!(target instanceof Element)) return;

    const routeLink = target.closest('a[data-dest]');

    if (!routeLink || !dealGrid.contains(routeLink)) return;

    event.preventDefault();
    selectDestination(routeLink.dataset.dest);
  });
}

/* =========================================================
   6. Load deals from the backend
   ========================================================= */

let deals = [];

if (dealGrid) {
  fetch('/api/deals')
    .then(async (response) => {
      if (!response.ok) {
        throw new Error('Could not load deals');
      }

      return response.json();
    })
    .then((data) => {
      deals = Array.isArray(data.deals) ? data.deals : [];
      renderDeals(deals);
    })
    .catch((error) => {
      console.error('GetOffDeals: failed to load deals:', error);

      dealGrid.innerHTML = `
        <p class="deal-empty">
          Could not load destination inspiration.
          Please refresh the page.
        </p>
      `;
    });
}

/* =========================================================
   7. Destination filters
   ========================================================= */

document.querySelectorAll('.filter').forEach((button) => {
  button.addEventListener('click', () => {
    document.querySelectorAll('.filter').forEach((item) => {
      item.classList.toggle('active', item === button);
    });

    renderDeals(deals, button.dataset.filter || 'all');
  });
});


/* =========================================================
   8. Flight search — redirect to Travelpayouts widget
   ========================================================= */

if (flightSearchForm) {
  flightSearchForm.addEventListener('submit', (event) => {
    event.preventDefault();

    const status = $('#search-status');

    const origin = originInput?.value.trim().toUpperCase() || '';
    const destination =
      destinationInput?.value.trim().toUpperCase() || '';
    const departure = departureInput?.value || '';
    const returnDate = returnInput?.value || '';
    const adults = $('#adults')?.value || '1';

    if (!origin || !destination) {
      if (status) {
        status.className = 'search-status error';
        status.textContent =
          'Please select an origin and destination.';
      }
      return;
    }

    if (departure && returnDate && returnDate <= departure) {
      if (status) {
        status.className = 'search-status error';
        status.textContent =
          'Your return date must be after your departure date.';
      }
      return;
    }

    const params = new URLSearchParams({
      origin,
      destination,
      adults
    });

    if (departure) params.set('departure', departure);
    if (returnDate) params.set('return', returnDate);

    window.location.href = `/flights?${params.toString()}`;
  });
}

/* =========================================================
   9. Newsletter signup
   ========================================================= */

const newsletterForm = $('#newsletter-form');

if (newsletterForm) {
  newsletterForm.addEventListener('submit', async (event) => {
    event.preventDefault();

    const status = $('#newsletter-status');
    const emailInput = $('#email');
    const consentInput = $('#newsletter-consent');

    if (!status || !emailInput || !consentInput) return;

    status.textContent = 'Saving your signup…';

    try {
      const response = await fetch('/api/newsletter', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          email: emailInput.value,
          consent: consentInput.checked,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || 'Signup failed.');
      }

      status.textContent = data.message || 'Signup successful.';
      emailInput.value = '';
      consentInput.checked = false;
    } catch (error) {
      status.textContent =
        error.message || 'Unable to save your signup.';
    }
  });
}

/* =========================================================
   10. Mobile navigation
   ========================================================= */

const menuToggle = $('.menu-toggle');

if (menuToggle) {
  menuToggle.addEventListener('click', () => {
    const links = $('.nav-links');

    if (!links) return;

    const open = links.classList.toggle('mobile-open');

    menuToggle.setAttribute('aria-expanded', String(open));
  });
}

/* =========================================================
   11. Welcome modal
   ========================================================= */

(() => {
  const modal = $('#welcome-modal');

  if (!modal) return;

  const closeButton = $('.welcome-modal-close');
  const exploreButton = $('#welcome-explore');

  if (!closeButton || !exploreButton) return;

  let previousFocus = null;

  function closeWelcomeModal() {
    modal.hidden = true;
    modal.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('welcome-modal-open');

    if (previousFocus?.isConnected) {
      previousFocus.focus();
    }
  }

  function openWelcomeModal() {
    previousFocus = document.activeElement;

    modal.hidden = false;
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('welcome-modal-open');

    closeButton.focus();
  }

  // Consume the one-time flag so refreshes won't reopen the modal.
  try {
    if (
      sessionStorage.getItem('getoffdeals_show_welcome') === '1'
    ) {
      sessionStorage.removeItem('getoffdeals_show_welcome');
      openWelcomeModal();
    }
  } catch (error) {
    console.warn('Welcome modal session storage unavailable:', error);
  }

  closeButton.addEventListener('click', closeWelcomeModal);
  exploreButton.addEventListener('click', closeWelcomeModal);

  modal.addEventListener('click', (event) => {
    if (event.target === modal) {
      closeWelcomeModal();
    }
  });

  document.addEventListener('keydown', (event) => {
    if (modal.hidden) return;

    if (event.key === 'Escape') {
      closeWelcomeModal();
      return;
    }

    // Keep keyboard focus inside the modal while it is open.
    if (event.key === 'Tab') {
      const focusable = [closeButton, exploreButton];
      const first = focusable[0];
      const last = focusable[focusable.length - 1];

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (
        !event.shiftKey &&
        document.activeElement === last
      ) {
        event.preventDefault();
        first.focus();
      }
    }
  });
})();

/* =========================================================
   12. Rotating travel showcase
   Changes themes every 10 minutes.
   The ticket remains decorative and does not trigger searches.
   ========================================================= */

(() => {
  const ticket = $('#rotating-ticket');
  const art = $('.hero-art');

  if (!ticket || !art) return;

  const fields = {
    number: $('#ticket-number'),
    kicker: $('#ticket-kicker'),
    originLabel: $('#ticket-origin-label'),
    origin: $('#ticket-origin'),
    originName: $('#ticket-origin-name'),
    destinationLabel: $('#ticket-destination-label'),
    destination: $('#ticket-destination'),
    destinationNote: $('#ticket-destination-note'),
    footer: $('#ticket-footer'),
  };

  const heroTitle = art.querySelector('.hero-destination strong');
  const heroKicker = art.querySelector('.destination-kicker');
  const heroRoute = art.querySelector('.route-line');

  const themes = [
    {
      id: 'international',
      number: '✳ 01',
      kicker: 'TAKEOFF / TRAVEL NOTE',
      originLabel: 'DEPARTING FROM',
      origin: 'AUH',
      originName: 'Abu Dhabi',
      destinationLabel: 'DESTINATION',
      destination: 'ANYWHERE',
      destinationNote: 'Choose your mood',
      footer: 'EXPLORE THE WORLD',
      heroKicker: 'YOUR NEXT PIN ON THE MAP',
      heroTitle: 'Somewhere<br>beautiful.',
      heroRoute: 'AUH <b>──── ✈ ────</b> WORLD',
    },
    {
      id: 'philippines',
      number: '✳ 02',
      kicker: 'ISLAND HOPPING / TRAVEL NOTE',
      originLabel: 'START YOUR JOURNEY',
      origin: 'MNL',
      originName: 'Manila',
      destinationLabel: 'EXPLORE LOCALLY',
      destination: 'PHILIPPINES',
      destinationNote: 'Islands, beaches & more',
      footer: 'DISCOVER THE ISLANDS',
      heroKicker: 'YOUR NEXT PHILIPPINE ESCAPE',
      heroTitle: 'Paradise is<br>closer.',
      heroRoute: 'MNL <b>──── ✈ ────</b> ISLANDS',
    },
    {
      id: 'worldwide',
      number: '✳ 03',
      kicker: 'GLOBAL GETAWAYS / TRAVEL NOTE',
      originLabel: 'DEPARTING FROM',
      origin: 'AUH',
      originName: 'Abu Dhabi',
      destinationLabel: 'NEXT ADVENTURE',
      destination: 'THE WORLD',
      destinationNote: 'New cities, new stories',
      footer: 'FIND YOUR NEXT ESCAPE',
      heroKicker: 'THE WORLD IS WAITING',
      heroTitle: 'Go further.<br>Feel more.',
      heroRoute: 'AUH <b>──── ✈ ────</b> WORLD',
    },
  ];

  let currentIndex = 0;
  let rotationTimer = null;
  let transitionTimer = null;

  function showTheme(index) {
    currentIndex = (index + themes.length) % themes.length;

    const theme = themes[currentIndex];

    if (transitionTimer !== null) {
      window.clearTimeout(transitionTimer);
    }

    ticket.classList.add('is-changing');

    transitionTimer = window.setTimeout(() => {
      ticket.dataset.theme = theme.id;
      art.dataset.theme = theme.id;

      Object.entries(fields).forEach(([key, element]) => {
        if (element) {
          element.textContent = theme[key];
        }
      });

      if (heroKicker) {
        heroKicker.textContent = theme.heroKicker;
      }

      // These HTML fragments are fixed strings defined above.
      if (heroTitle) {
        heroTitle.innerHTML = theme.heroTitle;
      }

      if (heroRoute) {
        heroRoute.innerHTML = theme.heroRoute;
      }

      ticket.classList.remove('is-changing');
      transitionTimer = null;
    }, 180);
  }

  function startRotation() {
    window.clearInterval(rotationTimer);

    rotationTimer = window.setInterval(() => {
      showTheme(currentIndex + 1);
    }, 10 * 60 * 1000);
  }

  // Start with the Abu Dhabi international theme.
  showTheme(0);
  startRotation();

  // Optional testing from the browser console.
  window.getOffDealsNextTheme = () => {
    showTheme(currentIndex + 1);
  };

  window.getOffDealsTheme = (index) => {
    const numericIndex = Number(index);

    if (Number.isInteger(numericIndex)) {
      showTheme(numericIndex);
    }
  };
})();
