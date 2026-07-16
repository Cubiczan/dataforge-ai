# 3-Minute Demo Video Script — DataForge AI

**Audience**: Devpost judges (Build with DataHub: The Agent Hackathon — Production ML Agents track)
**Duration**: ~2:55 (target under 3:00 hard limit)
**Format**: Narrated screen recording + title cards. Audio: TTS narration (saved as `assets/demo_narration.mp3`).
**Visual style**: Dark terminal on left, DataHub UI on right, occasional title cards.

---

## Shot list

### [0:00–0:15] Title card

**Visual**: Thumbnail image (`assets/thumbnail.png`) full-screen, fades to title text:
> **DataForge AI**
> *Production ML observability for the DataHub lineage graph*
> *Build with DataHub hackathon — Production ML Agents track*

**Narration (15s)**:
> "Production ML models fail silently — a feature stops refreshing, a schema drifts, a distribution shifts. DataForge AI is an agent that watches the DataHub lineage graph, detects those silent failures, and writes incidents back into DataHub so downstream agents inherit the context."

---

### [0:15–0:40] The problem (terminal screen)

**Visual**: Terminal window. Type commands live:
```bash
$ cat .env.example | grep -E '^(FRESHNESS|DISTRIBUTION|LLM)'
```

**Narration (25s)**:
> "Here's the setup. We have a DataHub instance running locally, an ML model — CritMin, a critical-mineral risk scorer — registered in the lineage graph, and three feature pipelines feeding it. The model serves predictions in production, but nothing watches whether its inputs are healthy. That's the gap DataForge AI fills."

---

### [0:40–1:15] Bring up DataHub + run the agent

**Visual**: Split screen — left: terminal, right: DataHub UI (http://localhost:9002) showing the CritMin ML model's lineage graph (datasets → feature group → model).

**Terminal**:
```bash
$ bash scripts/setup_datahub.sh    # already done, just show output tail
$ python scripts/seed_demo_data.py --plant-freshness-issue
$ dataforge demo
```

**Narration (35s)**:
> "We start DataHub with docker quickstart, ingest the demo datapack — that registers the nyc-taxi datasets and the CritMin ML model in the graph. Then we plant a freshness issue: the nyc-taxi rides dataset hasn't been updated in 36 hours, well past the 24-hour SLA. Now we run the agent."

---

### [1:15–2:00] Agent output — three findings

**Visual**: Terminal showing the agent's Rich-formatted output:
```
Scanning 1 ML model(s) for silent failures...

Model: CritMin Risk Scorer  urn:li:mlModel:...
Type           Severity   Target                                          Title
freshness      WARN       urn:li:dataset:...nyc_taxi.rides...            Freshness SLA violation: 36.0h old
schema         CRITICAL   urn:li:dataset:...nyc_taxi.rides...            Schema drift detected (vendor_id removed)
distribution   CRITICAL   urn:li:mlFeature:critmin.sentiment_polarity    PSI=0.412, KS p=0.0012

3 incident(s) now visible in DataHub UI → Incidents tab.
```

**Narration (45s)**:
> "The agent walks upstream from the CritMin model, runs three detectors on each entity, and finds three issues. First — freshness: the rides dataset is 36 hours old, past the SLA. Second — schema drift: the vendor_id column was dropped since the last scan. Third — distribution shift: the sentiment_polarity feature has a PSI of 0.41, well above the 0.20 threshold. Each finding is wrapped with structured evidence and an LLM-drafted resolution note."

---

### [2:00–2:40] Write-back to DataHub (the part judges care about)

**Visual**: Switch to DataHub UI. Navigate to the nyc-taxi rides dataset page → "Incidents" tab. Show three incidents listed with severity badges. Click into the distribution-shift incident — show the LLM-drafted description + resolution note.

**Narration (40s)**:
> "Here's the key part — these aren't stored in a side database. The agent writes them back to DataHub as DataHubIncidentProperties aspects on the failing entities. So now, anyone — or any agent — looking at the nyc-taxi dataset or the CritMin model sees the incidents right there in the graph. The next agent that picks up this model doesn't start from scratch. It inherits the context we just wrote."

---

### [2:40–2:55] Closing card

**Visual**: Fade to closing card:
> **DataForge AI**
> *Reads metadata. Writes incidents. Closes the loop.*
>
> github.com/Cubiczan/dataforge-ai  ·  Apache 2.0
> *Built for the Build with DataHub hackathon*

**Narration (15s)**:
> "DataForge AI: an agent that reads the DataHub lineage graph, detects silent ML failures, and writes incidents back so the next agent inherits the context. Apache 2.0, link in the description. Thanks for watching."

---

## Recording notes for the user

1. **Record in 1920x1080** (YouTube will downscale cleanly; avoids letterboxing).
2. **Use OBS Studio** (free) or QuickTime screen recording.
3. **Terminal**: Use a dark theme with a large font (18–20pt). iTerm2 / Windows Terminal both work.
4. **DataHub UI**: Run locally at `http://localhost:9002`. Have the dataset + model pages pre-loaded in browser tabs to avoid lag during the recording.
5. **Audio**: Use the generated `assets/demo_narration.mp3` as the voice track. Mute system audio during recording to avoid echo. If you prefer your own voice, the script above is ~325 words — about 2:50 at natural pace.
6. **Title cards**: Easy to make in Figma / Canva / Keynote. Use the thumbnail image as the title-card background.
7. **Captions**: Auto-generate from the narration MP3 via YouTube Studio after upload — judges may watch with sound off.

## Narration audio generation

The narration script above is split into 6 segments. Total word count: ~325 words (target pace 110 wpm = ~2:57). The TTS audio is generated by running:

```bash
python /home/z/my-project/scripts/generate_narration.py
```

This produces `/home/z/my-project/download/dataforge-ai/assets/demo_narration.mp3` (~3:00) which you can drop directly onto your screen-recording timeline.
