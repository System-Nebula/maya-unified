# Maya Browser Companion

The single browser capture package for Maya. It builds Chromium, Firefox, and a
privileged Chromium developer variant from shared TypeScript sources and can
send captures to either the legacy Maya gateway or the paired Lamia v1 API.

```bash
npm install
npm run check
npm test
npm run build
```

Load `dist/chromium`, `dist/firefox`, or `dist/chromium-devtools`. The developer
variant alone requests Chromium's `debugger` permission for DOMSnapshot and
AXTree capture.

The legacy destination is selected by default. Configure its gateway URL and
capture token in extension options. To use Lamia v1, install and register
`lamia-browser-host`, then explicitly select **Lamia v1** in options.

The panel and context menus support page, selection, screenshot, link, and image
capture. Captures never fall back silently from one destination to the other.

## Source-aware capture

Version 0.2 adds deterministic source context for Grok projects and
conversations. A capture of `grok.com/project/<id>` records the immutable source
project ID, a `urn:maya:chat:grok:project:<id>` canonical name, and the unique
conversation links currently exposed by the page. Conversation captures use
`urn:maya:chat:grok:conversation:<id>` identities.

The extension only reports source identity and observed links. Durable project
membership, pagination, semantic indexing, and ontology projection remain
gateway responsibilities; mutable project titles are never treated as IDs.

For the privileged remote-control development profile, run:

```bash
scripts/maya-browser-remote.sh 'https://grok.com/project/<id>?tab=conversations'
```

This launches the unpacked `chromium-devtools` build with its stable extension
ID and a loopback-only CDP endpoint at `http://127.0.0.1:9223`. It deliberately
does not start or configure a capture gateway; remote browser control and the
optional Lamia persistence destination have separate lifecycles.
