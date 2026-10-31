# RESQ SOS: offline emergency page (Part 1, Stages 1-5)

The phone page reads live GPS, builds `TYPE | STATUS | LAT,LON` (for example
`FLOOD | TRAPPED | 12.93450,77.61230`) and opens the SMS app with the gateway
number and text prefilled. After one visit with internet, a service worker lets
it open with no internet at all. The victim presses Send in the SMS app.

## Run it (first time)
1. Install Node.js 20.19 or newer (https://nodejs.org).
2. Copy `.env.example` to `.env.local` and put your real gateway number in it
   (digits, optional leading +). Both files stay in the project root.
3. `npm install`
4. `npm run check`   (unit tests + type-check + build + build check; all must pass)

## Everyday commands
| Command | What it does |
| --- | --- |
| `npm run dev` | Dev server with a dev panel (test coordinates). No offline support in dev. |
| `npm run build` | Production build into `dist/` (fails if the gateway number is missing). |
| `npm run preview` | Serves the production build at http://localhost:4173 (offline works here). |
| `npm run check` | Tests + type-check + build + build check. Run before every deploy. |
| `npm run check:live -- https://your-address +91XXXXXXXXXX` | Tests a deployed site. |
| `python tests/e2e/regression.py` | Optional: 49 real-browser checks (see below). |

## See the offline behaviour on your laptop
1. `npm run build`, then `npm run preview`, open http://localhost:4173
2. DevTools > Application > Service Workers: "activated and is running".
3. Network tab > tick Offline, reload: the page still loads.

## Try it on a phone
GPS only works on https. Run `npm run preview`, then in a second terminal
`cloudflared tunnel --url http://localhost:4173`, and open the https:// link it prints.
For the real offline demo, deploy to a fixed address: see `DEPLOY.md`.

## Optional: full browser regression
```
pip install playwright
playwright install chromium
npm run build
python tests/e2e/regression.py
```
It covers the message format, live GPS, offline reload, iPhone link style,
GPS denied / timeout / revoked, plain http, a wiped cache and its repair,
install prompt, installed mode, sub-folder hosting and update flow.

## Project map
- `src/main.ts` page logic, `src/message.ts` message + sms link, `src/geo.ts` GPS,
  `src/pwa.ts` service worker + install, `src/readiness.ts` checklist
- `sw-template.js` the service worker (built into `dist/sw.js` with a version hash)
- `public/manifest.webmanifest`, `public/icons/` installable app files
- `vite.config.ts` build plugin (refuses a missing number, strips the dev panel, writes sw.js)
- `scripts/` build check and live-site check, `tests/` service worker tests and browser regression

## If something goes wrong
| You see | Fix |
| --- | --- |
| SEND SOS stays grey and the link area mentions the gateway number | `.env.local` is missing or wrong. Fix it and restart `npm run dev`. |
| "GPS is blocked: this page is not HTTPS" | Open the https:// link (tunnel or deployed), not http://192.168.x.x. |
| "Location permission is off" | Allow Location for the site in the browser settings, then tap Update my location. |
| "Not ready yet" checklist | Do the items listed under it while you still have internet. |
| Build says VITE_GATEWAY_NUMBER is missing | Set it in `.env.local` (local) or in the host's environment variables (deploy). |
| Old version still shows after a redeploy | Open the page once with internet, then reload once more. |
