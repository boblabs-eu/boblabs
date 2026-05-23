> **Document Type: Use Case / Example** — This document is a French-language example of how Bob Labs agents can be configured for recruitment automation. It is not core platform documentation.

🧠 1) Vue d’ensemble de la “machine”

👉 Objectif :

automatiser tout le funnel : prospection → sourcing → qualification → placement

🧩 Les grands blocs d’agents
Acquisition clients
Acquisition candidats
Qualification
Matching
Closing
⚙️ 2) Stack d’agents complète
🟣 1. Agent de prospection client (Business Dev AI)
🎯 Objectif :

Trouver des entreprises qui recrutent

🔧 Ce qu’il fait :
scrape offres d’emploi (LinkedIn, WelcomeToTheJungle…)
détecte besoins actifs
enrichit les leads (taille, secteur, stack)
⚡ Actions :
envoie emails personnalisés
messages LinkedIn automatisés
relances
🧠 Stack technique :
scraping (Apify, PhantomBuster)
enrichment (Clearbit, Dropcontact)
LLM pour personnalisation
🔵 2. Agent de sourcing candidats
🎯 Objectif :

Trouver des profils pertinents

🔧 Actions :
scrape LinkedIn / GitHub / CVthèques
construit base candidats
score profils
🧠 Critères :
skills
expériences
mobilité
cohérence CV
🟢 3. Agent d’analyse de CV
🎯 Objectif :

Qualifier automatiquement les candidats

🔧 Ce qu’il fait :
parse CV
extrait :
compétences
années d’expérience
techno
détecte incohérences
⚡ Output :
score de “fit”
résumé structuré
🟡 4. Agent de pré-entretien (screening)
🎯 Objectif :

remplacer le premier call recruteur

🔧 Format :
chatbot ou call vocal (type VAPI)
Questions :
motivation
dispo
salaire
niveau technique

👉 Peut même faire :

mini test technique
QCM
🔴 5. Agent de matching (le cerveau)
🎯 Objectif :

associer candidats ↔ missions

🔧 Fonctionnement :
input :
fiche poste
base candidats
output :
shortlist automatique
🧠 Méthodes :
embeddings (similarité sémantique)
scoring multi-critères
🟠 6. Agent de génération de shortlist
🎯 Objectif :

envoyer au client des profils propres

Output :
CV reformatté
résumé clair
points forts/faibles

👉 format “cabinet premium”

🟤 7. Agent de suivi candidat
🎯 Objectif :

ne perdre aucun candidat

🔧 Actions :
relances automatiques
suivi pipeline
notifications
⚫ 8. Agent closing / négociation
🎯 Objectif :

convertir en placement

🔧 Actions :
aide à la négo salaire
propose arguments
génère mails
🔁 3) Workflow complet automatisé
1. Prospect détecté

→ Agent prospecting

2. Besoin identifié

→ Agent compréhension fiche poste

3. Candidats sourcés

→ Agent sourcing

4. CV analysés

→ Agent CV

5. Screening

→ Agent entretien

6. Matching

→ Agent matching

7. Envoi client

→ Agent shortlist

8. Suivi & closing

→ Agents follow-up + closing

🧰 4) Stack technique concrète (exemple)
Orchestration
LangChain / Flowise / CrewAI
LLM
GPT / Claude / Mistral
Base de données
PostgreSQL (structuré)
Pinecone / Weaviate (vector DB)
Scraping
Apify
PhantomBuster
Automatisation
n8n / Make
CRM
HubSpot / Attio
🧠 5) Ce qui fait la différence (très important)

👉 Ce n’est PAS les agents individuellement
👉 C’est le scoring + la donnée

Les vrais avantages compétitifs :
qualité du matching
vitesse
qualité des données candidats
personnalisation des messages
⚠️ 6) Les limites à connaître

Même avec une stack parfaite :

❗ le closing reste humain (souvent)
❗ les bons candidats sont rares → besoin de chasse fine
❗ la relation client compte énormément
🚀 Résumé

👉 Ton cabinet devient :

une pipeline automatisée de détection → qualification → matching → placement

Avec :

80% automatisé
20% humain (closing + relation)