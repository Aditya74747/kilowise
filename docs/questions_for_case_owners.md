# Questions for the case owners (ALTYCA)

Short, plain questions to ask the challenge givers. Write their answer in the right-hand column, then tell the team
(or Claude) so the project can be updated. If time is short, ask the ones marked **★** first.

## 1. The targets

| # | Question | Answer |
|---|---|---|
| 1 ★ | The task says −40 % CO₂, −25 % cost and at most 15 person-days. Are these strict limits we must reach, or goals to aim for? || Goals. The case owner tested them on this data himself and they are achievable. |
| 2 ★ | If a team reaches −38 % CO₂ instead of −40 %, does it fail, or does it just get fewer points? | |
| 3 | Is it better to go far beyond the targets, or to reach them exactly with less risk? | |
| 4 | Do all three targets count the same, or is one more important than the others? | |
| 5 | Is the −40 % CO₂ target measured with the electricity mix at the data-centre location, as the task says? Or can green electricity certificates count too? || Depends on where the server is and how it gets its electricity. Factors are assumptions based on facts from different sources; estimating them is expected. |
| 6 | Does the −25 % cost target mean savings per year, after the measures are in place? | |
| 7 | Does the 15 person-days budget mean only the one-time work to set up the measures, or also the work afterwards? | |
| 8 ★ | If our result reaches the target with normal assumptions but not with very careful assumptions, does that count as reached? | |

## 2. How you check our results

| # | Question | Answer |
|---|---|---|
| 9 ★ | When you recalculate our results, do you include the one-off events (the AI bug in March 2026 and the data migration in January 2026), or do you leave them out? || Leave the one-off events out (normalised baseline). Matches what we do. |
| 10 ★ | Do you recalculate our CO₂ with your own conversion factors, or do you use the CO₂ figures we give you? | |
| 11 | For the data centre in Zurich, should we use the Swiss electricity mix *including* imports, or the mix *produced in* Switzerland? | |
| 12 ★ | Do you check our effort estimates in person-days, or do you accept our numbers? Is exactly 15 person-days still within the budget? | |
| 13 ★ | Should savings be counted for a full year, even when a measure can only start later, for example at a contract renewal? || Show it as a forecast: what the SME will pay with and without our measures over the next years, as a comparison chart. |

## 3. What we are allowed to change

| # | Question | Answer |
|---|---|---|
| 14 | Can cancelling or reducing software subscriptions count as a measure, even if it saves money but no CO₂? | |
| 15 | Are we allowed to move a server cluster to a different data centre, for example from Frankfurt to Zurich? | |
| 16 | If a system switches itself off at night and needs 5 to 10 minutes to start again when someone uses it, is that acceptable? || Acceptable for now; the data already contains such cases. |
| 17 | May we delete old servers that nobody has logged into for over a year, if we keep a backup first? | |
| 18 | Do price changes from the provider, for example a cheaper Copilot licence, count as a saving? | |
| 19 | Are one-time purchases or fees (for example new hardware or a migration fee) allowed? Do they count against the budget, or only person-days? | |

## 4. New ideas that could change the approach

| # | Question | Answer |
|---|---|---|
| 20 ★ | Can we suggest running small AI models on the company's own computers or servers instead of paid cloud AI services? || Both local LLMs and closed models (ChatGPT, Claude) are valid. SMEs usually integrate the big models; local models bring a security argument. The right choice depends on the problem the SME wants to solve. |
| 21 | If yes: is that electricity counted with the Swiss mix at the office in Basel? And do the computer and its manufacturing count too? | |
| 22 | Can we suggest switching to a Swiss-hosted AI service (for example the Swiss open model Apertus via Swisscom) instead of providers in the EU or USA? | |
| 23 | Can we suggest using smaller, cheaper AI models for simple tasks (sorting, summaries, translations), if the quality stays good enough? | |
| 24 | Can we suggest running flexible jobs at the times of day when the electricity is cleanest? || Yes, if based on real facts about when the grid is cleanest. |
| 25 | Can we suggest moving work to a cloud provider or region with cleaner electricity, even if it costs a little more? | |
| 26 | Can we suggest buying green electricity certificates, or does only a real reduction in electricity use count? || Good for the project if we have the data to do it; it stays an assumption, but implementing it is welcome. |
| 27 | Can we suggest replacing old servers with fewer, newer and more efficient ones? | |
| 28 | Should we count the CO₂ from manufacturing hardware, or only the electricity it uses? | |
| 29 | Can we suggest deleting old data and backups that nobody uses, or are there rules (for example legal storage periods) we should know about? | |
| 30 | Can we suggest asking the providers for their real energy data instead of using estimates? | |

## 5. The data

| # | Question | Answer |
|---|---|---|
| 31 ★ | Should AI services and SaaS tools be part of the CO₂ total, even though we don't know where their data centres are? | |
| 32 | Did you hide specific problems in the data on purpose? Is there a list you will check us against? | |
| 33 | The location list says we don't use AWS in Zurich, but the invoices show costs there. Which one is right? | |
| 34 | The AI invoice is about 6 % higher than the usage log. Which number should we use? | |

## 6. Submission and pitch

| # | Question | Answer |
|---|---|---|
| 35 ★ | What exactly should we hand in: a file, a link or a folder? Is there a size limit? | |
| 36 ★ | Will you run our tool yourselves, or only watch our demo? | |
| 37 | Can we use our own laptop for the pitch, and is there internet in the room? | |
| 38 | Will the jury ask new questions during the pitch, or only the three example questions? | |
| 39 | May we add extra rows to the two templates, as long as we keep the column names? | |
| 40 | Will you test our tool with data from another company? | |

## 7. Scoring

| # | Question | Answer |
|---|---|---|
| 41 | For the bonus points, is it better to show many extra features or fewer features done very well? | |
| 42 | For "the energy of our own AI use", should we count only building the tool, or also training and running our AI assistant? | |


## Feedback from the case owner (project review)

- Visuals and the overall project look good. The numbers are correct; he has worked with this data before.
- The chatbot with RAG is a strong point.
- **Most important:** make the charts a **CEO-level dashboard**, one holistic picture that answers leadership's questions
  without clicking around, plus a separate **IT admin dashboard** for the technical detail. Be creative so the project
  stands out.

What we did with the answers:

- Overview is now a dashboard with two views, **Leadership** and **IT team** (tabs at the top of the Overview; link
  `index.html?view=it`). After his second review ("the first chart is not CEO level; show the most important metrics,
  more of the clear numbers from Action plan and Insights") the plan bars were replaced. Leadership: verdict line, six
  key-figure cards with trend lines (IT cost, CO₂, electricity, saved per year, payback, 3-year saving), the three target
  gauges, the 3-year outlook with and without the plan (answer to Q13), savings by measure (click to take one out),
  biggest waste found, decisions, monthly cost, spend by department, CO₂ sources, six questions answered from the data.
  IT team: key figures, kWh and CO₂ by grid and category, cleanest hours, hot list of the 10 largest CO₂ sources with
  their fix, change runbook, safeguards, ML watch list.
- Q1: targets are goals, but we keep reaching them (−48.8 % CO₂, −33.4 % cost, 15 PD); the safety margin stays.
- Q9: confirmed our normalised baseline.
- Q24: the hourly Swiss profile is based on Electricity Maps 2025 and the UNIGE hourly mix (cleanest around midday).
- Q26: the market-based view (guarantees of origin) is already a toggle under View; it stays information, not the target.
- Q20: done as the **Models** page: 20 open and closed models compared on the company's own token workload (size,
  capabilities, API price, CO₂ per token, 3-year outlook), where models are trained and what training cost, and the
  data-security point (open models can run in Switzerland or in-house). X7 still advises against the idle Frankfurt GPU.

---

## Notes for our team (not for the case owners)

What each answer would change in the project:

- **Targets (1–8).** Today: −48.8 % CO₂, −33.4 % cost, exactly 15.0 of 15 person-days; with very careful factors still
  −41.3 %. If the limits are strict, effort is our risk: free up half a day by simplifying a small measure. If going
  beyond the targets earns points and the budget is flexible, switch on the bonus measures B3–B5. If certificates count,
  our market-based result is −55 %.
- **Recalculation (9–13).** One-offs out (normalised baseline), consumption mix, mid factors and full-year savings are our
  current choices. A different answer changes the baseline or the savings; the app already has low/mid/high factors, the
  production-mix toggle and a "check against another baseline" field.
- **Allowed changes (14–19).** M7 and M8 (subscriptions, CHF 45k) carry the cost target; M3 is the relocation; M1 relies
  on auto-resume; M5 deletes the forgotten servers. A "no" on any of these needs a replacement measure.
- **New ideas (20–30).** Local AI models: today we recommend against running a model on the idle Frankfurt GPU (X7),
  because it keeps a server on 24/7 on a dirty grid. A small model on hardware in Basel would count with the Swiss
  mix (0.094 vs 0.22 kg/kWh for EU AI services), but the hardware purchase and its manufacturing CO₂ may count. Our own
  assistant is already a local model (Qwen2.5-1.5B), which is a good demo point. Answers to 22–26 decide whether the
  Swiss model routing, carbon-aware timing, greener regions or certificates become real measures instead of
  information. 27–30 open measures we have not built yet (hardware refresh, data deletion, real provider data).
- **Data (31–34).** If AI and SaaS are out of scope, our weakest assumptions (EU mix, SaaS energy per user) disappear.
- **Submission (35–40).** Decides packaging: the chat model needs a GPU and an extra install; the core runs offline
  from the folder.
