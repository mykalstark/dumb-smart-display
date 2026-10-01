# Web interface redesign

## Current interface

The configuration page stacks software updates, location, module selection, expanded
module settings, hardware, after-hours options, and access controls in one long
column. Module selection and configuration are separated, enabled modules open
by default, and the page has no heading or active navigation indicator. The module
manager relies on dragging, truncates descriptions, dims disabled controls, and
has no named switches or touch/keyboard reorder alternative. Date fields and
keyboard focus lack consistent styling. The save bar gives no change feedback.

## Design and implementation plan

1. Establish a shared light theme with muted teal accents, readable typography,
   restrained borders, consistent spacing, and a responsive navigation rail.
2. Group settings into General, Module settings, After hours, Access, and Software.
   Keep all values in one real form so saving retains the complete configuration.
   Use keyboard-accessible tabs; show every section when JavaScript is unavailable.
3. Combine module enable switches and collapsed settings. Keep disabled modules
   readable, indicate their state with text, and open a module when enabling it.
   Reveal hidden invalid fields before browser validation focuses them.
4. Retain illustrative module previews, add enabled counts and configuration
   links, and provide move-up/down buttons alongside desktop dragging. These work
   with touch and keyboards. Show the actual enabled playback order.
5. Add consistent save feedback and warn before leaving unsaved edits. Clearly
   distinguish immediate photo uploads/deletions from settings saved on submission.
   Match the login screen and software-update dialog to the shared theme.
6. Verify desktop and narrow layouts, tab/accordion keyboard access, validation,
   module ordering, form payloads, time conversion, photo actions, and login. Run
   existing tests and commit/push the result on the work branch.

## Constraints

Use Flask/Jinja and local CSS/JavaScript without a frontend build, CDN, remote fonts,
icon libraries, or new runtime dependencies. Preserve configuration names, existing
routes, restart behavior, custom module order, and unrendered YAML keys. Browser
checks use a temporary configuration and mock service restarts and update streams;
they must not restart hardware services or update the live checkout.

## Verification

Run the Python regression suite with:

```sh
.venv/bin/python -m unittest discover -s tests -v
```

`node scripts/check_webui_browser.cjs` runs the interaction checks against its own
Flask fixture on an ephemeral local port. The fixture uses temporary configuration
and uploads, mocks service restarts, and blocks real software updates. It checks
keyboard tabs, dirty state, hidden-field validation, decimal coordinates, time
conversion, photo actions, events, update dialog focus, dragging, reorder buttons,
save/reload persistence, login, and layout overflow at 320, 390, 768, 1024, and
1440 pixels. It requires Playwright and Chromium only for development; no browser
packages are added to the application runtime.

If Playwright is not available in your development environment:

```sh
npm install --prefix /tmp/display-ui-checks playwright
NODE_PATH=/tmp/display-ui-checks/node_modules node scripts/check_webui_browser.cjs
```

The runner uses `/usr/bin/chromium` when available, otherwise Playwright's installed
Chromium. Set `CHROMIUM_PATH` to use another installation and `PYTHON` to select a
Python interpreter with the application's dependencies.
