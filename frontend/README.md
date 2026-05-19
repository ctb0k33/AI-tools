# Daily Research Frontend

React + TypeScript dashboard for `daily_research_digest.json`.

## Run

Start the local Python API bridge from the project root:

```powershell
python -m tools.daily_research.dashboard_api
```

Then start the React app:

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

Open the URL printed by Vite. The app loads `public/sample/daily_research_digest.json` by default.

## Collecting From The UI

Use the date picker and `Collect Daily Data` button. The frontend calls:

```text
POST /api/collect
```

The API bridge runs:

```powershell
python -m tools.daily_research.daily_research_tool --date <YYYY-MM-DD> --profile-dir profiles\x_profile --config tools\daily_research\config\selected_x_profiles.config.json --output-dir outputs\daily_research
```

When the script finishes, the new JSON digest is loaded directly into the dashboard.

## Updating Data

Use `Load latest generated output`, the Upload JSON button, or replace:

```text
frontend/public/sample/daily_research_digest.json
```

with a newer file from:

```text
outputs/daily_research/<YYYY-MM-DD>/daily_research_digest.json
```
