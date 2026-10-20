# Download status icons

Status marks for finalized downloads, shared by the Downloads dropdown
(`src/downloadDropdown.ts`) and the Downloads page (`src/downloadsPage.ts`)
through `src/shared/downloadStatusIcons.ts`.

| File           | Finalize reason | Colour (set in CSS) |
| -------------- | --------------- | ------------------- |
| `done.svg`     | `done`          | green               |
| `failed.svg`   | `failed`        | red                 |
| `canceled.svg` | `canceled`      | muted grey          |

Same conventions as `src/titlebar-icons/`: 24x24 outline, `currentColor`,
inlined via Vite's `?raw` import.
