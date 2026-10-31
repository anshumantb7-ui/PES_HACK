# Stage 4: deploy and install on Phone A

Goal: Phone A opens the page from its home screen with Wi-Fi and mobile data OFF
(SIM active), shows live GPS, and opens the SMS app with
`TYPE | STATUS | LAT,LON` ready to send.

The page needs one visit WITH internet so the phone can save it. After that it
works offline. Use ONE fixed address; do not use a tunnel link for the real demo
(it changes every time and dies when your laptop stops).

## 1. Put the code on a host (pick one)

### A. Vercel from GitHub (recommended)
1. Push this folder to a GitHub repo. `.env.local` is git-ignored, so your number is not uploaded.
2. vercel.com > Add New > Project > import the repo. Vercel detects Vite
   (Build Command `npm run build`, Output Directory `dist`).
3. Before the first deploy: Settings > Environment Variables > add
   `VITE_GATEWAY_NUMBER` = your gateway number (digits, optional leading +), for Production.
4. Deploy. Your address is `https://<project>.vercel.app`.

### B. Vercel CLI (no GitHub)
```
npx vercel login
npx vercel link
npx vercel env add VITE_GATEWAY_NUMBER production
npx vercel --prod
```

### C. Netlify or Cloudflare Pages
Build command `npm run build`, publish/output directory `dist`, environment
variable `VITE_GATEWAY_NUMBER`. `public/_headers` is picked up automatically.

If the build says "VITE_GATEWAY_NUMBER is missing or invalid", the variable is
not set on the host. That check is deliberate: a wrong number would be saved on
victims' phones.

## 2. Check the live site from your laptop
```
npm run check:live -- https://<your-address> +91XXXXXXXXXX
```
Every line must say `ok` and it must end with `Live check passed`. It checks
HTTPS, every file the page needs, every file the offline cache will save, the
`sw.js` cache header, the manifest and icons, and that the number inside the
app is the one you expect.

## 3. Prepare Phone A (with internet ON)
1. Open `https://<your-address>` in Chrome (Android) or Safari (iPhone).
2. Tap Allow when it asks for location. Wait until the page shows the
   coordinates and the checklist says "Saved for offline use" with a tick.
3. Android: tap Install app (or menu > Install app). iPhone: Share > Add to Home Screen.
4. Open the app from its home screen icon once and let the GPS get a fix.
5. The page must say: "Ready: this phone can send an SOS with no internet."

## 4. The real offline test
1. Turn OFF Wi-Fi and mobile data. Keep the SIM active. Do NOT use airplane mode.
2. Close the app fully, then open it from the home screen icon.
3. Expected: page loads, Network says "No internet", coordinates appear
   (indoors can take a minute; go near a window), preview shows
   `FLOOD | TRAPPED | 12.xxxxx,77.xxxxx`.
4. Tap SEND SOS: the SMS app opens with the gateway number and the text ready.
5. Press Send. Phone B should receive the text.

## 5. After you change the app
Redeploy, then on each phone open the page once with internet. The new version
shows in the "Works offline" line (v...). The old copy is deleted automatically.

## Known limits
- iPhone Safari can delete saved site data after about a week of not using
  the site. Adding it to the home screen and opening it before the demo avoids this.
- iPhone may ask for location permission again each time the home-screen app
  starts. Test this on your exact iPhone and iOS version.
- The first GPS fix with no internet can take a minute or more. Warm it up once
  with internet on, as in step 3.4.
- The `sms:` link separator differs between Android (`?body=`) and iPhone
  (`&body=`). The page picks it automatically; confirm on real devices.
