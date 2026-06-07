/**
 * Lightweight i18n for the Bob Labs marketing/public site.
 * Single dictionary scoped to the landing page, docs chrome, trial form,
 * and login page.
 *
 * - Single `messages` map keyed by language → flat keys.
 * - `useT()` returns `t(key, vars?)` with `{var}` interpolation.
 * - Lang persists to localStorage and falls back to navigator language.
 */

import React, { createContext, useContext, useState, useCallback, useMemo, useEffect } from 'react';

const STORAGE_KEY = 'bob_lang';
const SUPPORTED = ['en', 'fr'];
const DEFAULT_LANG = 'en';

function detectInitial() {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored && SUPPORTED.includes(stored)) return stored;
    // Honor explicit /fr URL on first visit
    if (typeof window !== 'undefined' && window.location?.pathname?.startsWith('/fr')) return 'fr';
    const nav = (window.navigator?.language || '').slice(0, 2).toLowerCase();
    if (SUPPORTED.includes(nav)) return nav;
  } catch { /* ignore */ }
  return DEFAULT_LANG;
}

export const messages = {
  en: {
    // Header / nav
    'nav.brand': 'Bob Labs',
    'nav.product': 'Product',
    'nav.platform': 'Platform',
    'nav.features': 'Features',
    'nav.deploy': 'Deploy',
    'nav.pricing': 'Pricing',
    'nav.docs': 'Docs',
    'nav.blog': 'Blog',
    'nav.live': 'Live',
    'nav.showroom': 'Showroom',
    'nav.signin': 'Sign In',
    'nav.requestTrial': 'Request Trial',

    // Hero
    'hero.badge': 'Open Source · Self-Hosted · Full-Stack AI Agents',
    'hero.title.before': 'The full-stack',
    'hero.title.gradient': 'AI agent platform',
    'hero.title.after': 'your infrastructure was missing',
    'hero.sub': 'Bob Labs runs multi-agent labs, private RAG, GPU pipelines and a sandboxed tool runtime — on your own servers, in two commands. Configure everything visually, or ship your lab as a JSON file.',
    'hero.cta.start': 'Get Started',
    'hero.cta.preview': 'Dashboard preview',
    'hero.cta.github': 'View on GitHub',
    'hero.proof.private': 'Private by default',
    'hero.proof.noMarkup': 'No per-token markup',
    'hero.proof.unlimited': 'Unlimited labs & agents',
    'hero.proof.deploy': 'Deploy in 2 commands',

    // Product preview section
    'preview.overline': 'The Product',
    'preview.title': 'Take a tour of Bob Labs',
    'preview.lead': 'Real screenshots from a running deployment. Click a tab to peek inside.',

    // Core platform section
    'core.overline': 'Core Platform',
    'core.title.line1': 'The infrastructure layer',
    'core.title.line2': 'your AI agents are missing',

    // Features grid
    'features.overline': 'Everything in the box',
    'features.title': 'All the pieces. None of the lock-in.',
    'features.lead': 'Private or enterprise. Local or API. Visual or JSON. You choose every dimension.',

    // Deploy section
    'deploy.overline': 'Deploy',
    'deploy.title.before': 'From',
    'deploy.title.after': 'to running platform — in two commands.',
    'deploy.lead': 'No Kubernetes, no SaaS, no waiting list. Just Docker Compose on your server.',
    'deploy.copy.title': 'Two commands. Your stack. Your data.',
    'deploy.copy.b1.strong': 'One repo',
    'deploy.copy.b1.body': '— the entire platform, frontend + backend + GPU services.',
    'deploy.copy.b2.strong': 'One compose file',
    'deploy.copy.b2.body': '— pick the modules you want, leave the rest off.',
    'deploy.copy.b3.strong': 'Zero vendor calls',
    'deploy.copy.b3.body': '— works fully offline if all your models are local.',
    'deploy.copy.b4.strong': 'Versioned config',
    'deploy.copy.b4.body': '— labs as JSON, prompts in git, audit-ready.',
    'deploy.cta.docs': 'Read the install guide',
    'deploy.cta.github': 'View on GitHub',

    // Private vs Enterprise split
    'split.overline': 'Built for both',
    'split.title': 'Private power user or enterprise team — same platform.',
    'split.private.title': 'For private use',
    'split.private.b1': 'Run on your home server or workstation',
    'split.private.b2': 'Mix local Ollama models with API providers',
    'split.private.b3': 'Keep all documents and chats on your own disk',
    'split.private.b4': 'Author labs as JSON, share them on GitHub',
    'split.enterprise.title': 'For enterprise',
    'split.enterprise.b1': 'JWT auth, RBAC, admin panel, audit trail',
    'split.enterprise.b2': 'Share labs across teams with fine-grained access',
    'split.enterprise.b3': 'Deploy on-prem or in your own VPC',
    'split.enterprise.b4': 'Quote-based pilot, production and SLA support tiers',

    // Pricing
    'pricing.overline': 'Pricing',
    'pricing.title': 'Simple pricing. No per-token markup.',
    'pricing.openSource.title': 'Open Source',
    'pricing.openSource.price': 'Free',
    'pricing.openSource.body': 'Full platform, self-hosted, no restrictions.',
    'pricing.openSource.cta': 'Get Started',
    'pricing.pilot.title': 'Private Pilot',
    'pricing.pilot.body': "We deploy Bob Labs, configure your first workflow, and onboard your team.",
    'pricing.production.title': 'Production',
    'pricing.production.body': 'Full deployment with security review, integrations, and go-live support.',
    'pricing.support.title': 'Enterprise Support',
    'pricing.support.body': 'SLA-backed support, upgrade assistance, and quarterly reviews.',
    'pricing.custom': 'Custom',
    'pricing.cta.quote': 'Request a Quote',

    // CTA + footer
    'cta.title': 'Your servers. Your data. Your agents.',
    'cta.body': 'Run the full-stack AI platform on infrastructure you already trust — or talk to us about a managed deployment.',
    'cta.docs': 'Read the Docs',
    'cta.trial': 'Request Trial',

    'footer.tagline': 'Full-stack AI agent platform. Open source.',
    'footer.product.title': 'Product',
    'footer.product.tour': 'Tour',
    'footer.product.core': 'Core platform',
    'footer.product.features': 'Features',
    'footer.product.pricing': 'Pricing',
    'footer.resources.title': 'Resources',
    'footer.resources.docs': 'Documentation',
    'footer.resources.github': 'GitHub',
    'footer.resources.blog': 'Blog',
    'footer.company.title': 'Company',
    'footer.company.contact': 'Contact',
    'footer.company.trial': 'Request Trial',
    'footer.copyright': '© {year} Bob Labs. Open-source software under Apache 2.0 license.',

    // Quote modal
    'quote.title': 'Request a Quote',
    'quote.intro': "Tell us about your project and we'll prepare a tailored proposal.",
    'quote.success.title': 'Request Submitted',
    'quote.success.body': "Thank you! We'll review your request and get back to you shortly.",
    'quote.close': 'Close',
    'quote.field.name': 'Full name *',
    'quote.field.email': 'Work email *',
    'quote.field.company': 'Company / Organization',
    'quote.field.phone': 'Phone number',
    'quote.field.description': 'Describe your needs and use case',
    'quote.error.required': 'Name and email are required.',
    'quote.error.generic': 'Something went wrong. Please try again.',
    'quote.submit': 'Submit Request',
    'quote.submit.loading': 'Submitting…',

    // Plan labels (used as quote subjects)
    'plan.privatePilot': 'Private Pilot',
    'plan.production': 'Production',
    'plan.enterpriseSupport': 'Enterprise Support',

    // Trial request page
    'trial.title': 'Request Trial Access',
    'trial.intro': "Tell us about yourself and we'll set up a trial workspace for you.",
    'trial.success.title': 'Request Submitted',
    'trial.success.body': "Thank you! We'll review your request and get back to you shortly.",
    'trial.success.back': 'Back to Home',
    'trial.field.name': 'Full name *',
    'trial.field.email': 'Work email *',
    'trial.field.company': 'Company / Organization',
    'trial.field.role': 'Your role',
    'trial.field.purpose': 'What do you plan to use Bob Labs for?',
    'trial.error.required': 'Name and email are required.',
    'trial.error.generic': 'Something went wrong. Please try again.',
    'trial.submit': 'Submit Request',
    'trial.submit.loading': 'Submitting…',
    'trial.haveToken': 'Already have a token?',
    'trial.signIn': 'Sign in',

    // Login page
    'login.title': 'Sign in to your workspace',
    'login.intro': 'Enter the access token provided by your administrator.',
    'login.placeholder': 'bob_xxxxxxxxxxxxxxxx',
    'login.error': 'Invalid or expired access token.',
    'login.submit': 'Sign In',
    'login.submit.loading': 'Validating…',
    'login.noToken': "Don't have a token?",
    'login.requestTrial': 'Request trial access',

    // Docs page chrome
    'docs.title': 'Documentation',
    'docs.search': 'Search docs…',
    'docs.loading': 'Loading…',
    'docs.error': 'Failed to load document.',
    'docs.notice.lang': 'Documentation is available in English. UI labels are translated.',

    // Preview tabs
    'preview.tab.dashboard': 'Lab Dashboard',
    'preview.tab.lab': 'Inside a Lab',
    'preview.tab.lab2': 'Lab — agent view',
    'preview.tab.agent': 'Agent Templates',
    'preview.tab.memories': 'Memories (shareable within a lab)',
    'preview.tab.models': 'Inference Feed',
    'preview.tab.stats': 'Inference Stats',
    'preview.tab.dispatch_live': 'Load balancer',
    'preview.tab.live': 'Live View',
    'preview.tab.live_attach': 'Live · outputs view',

    // Core categories
    'core.enterprise.title': 'Enterprise Grade',
    'core.enterprise.sub': 'Auth, RBAC, sharing, admin panel',
    'core.enterprise.b1': 'User authentication (JWT) · admin panel · audit trail',
    'core.enterprise.b2': 'Share labs across teams with fine-grained access',
    'core.enterprise.b3': 'Quote requests, trial onboarding, support tiers',
    'core.data.title': 'Data Sovereignty',
    'core.data.sub': 'Full control. Full privacy. Always your data.',
    'core.data.b1': 'Self-hosted PostgreSQL · vector RAG · LightRAG knowledge graph',
    'core.data.b2': 'No data ever leaves your perimeter',
    'core.data.b3': 'Per-lab isolation · per-collection access control',
    'core.agents.title': 'Agents Without Limits',
    'core.agents.sub': 'Local or API · memory · tools · everything tunable',
    'core.agents.b1': 'API providers (OpenAI, Anthropic, …) and local (Ollama, vLLM)',
    'core.agents.b2': 'Persistent memory · full conversation history',
    'core.agents.b3': 'Tools: shell, python, browser, search, RAG, db, web3 — and a lot more',
    'core.labs.title': 'Labs & Orchestration',
    'core.labs.sub': 'Orchestrator · agents · resources · anti-loop',
    'core.labs.b1': 'Orchestrator coordinates specialist agents over multi-step plans',
    'core.labs.b2': 'Per-lab strategy prompts · in/out file resources',
    'core.labs.b3': 'Anti-loop system detects repetition and self-recovers',
    'core.labs.b4': 'Unlimited labs, agents, providers',
    'core.hardware.title': 'Hardware & Dispatch',
    'core.hardware.sub': 'GPU dispatcher · auto-discovery · hot-swap',
    'core.hardware.b1': 'Agent auto-discovery across machines',
    'core.hardware.b2': 'Smart dispatcher routes models to the right GPU',
    'core.hardware.b3': 'Pause/resume long jobs · queue across hosts',
    'core.config.title': 'Fully Configurable',
    'core.config.sub': 'Every prompt, model, agent, tool — yours to shape',
    'core.config.b1': 'Configure visually in the UI… or import / export labs as JSON',
    'core.config.b2': 'Write your entire lab as a JSON file and ship it',
    'core.config.b3': 'Override any prompt, swap any model, restrict any tool',

    // Features grid
    'feat.auth.title': 'User auth & admin',
    'feat.auth.body': 'JWT auth, role-based access, admin panel, audit trail, share labs.',
    'feat.private.title': 'Private by default',
    'feat.private.body': 'Self-hosted PostgreSQL, vector RAG, LightRAG. Nothing leaves your network.',
    'feat.models.title': 'Any model, any provider',
    'feat.models.body': 'OpenAI, Anthropic, Ollama, vLLM, HF — local + API together with auto-fallback.',
    'feat.memory.title': 'Memory & history',
    'feat.memory.body': 'Persistent per-agent memory and full conversation history across sessions.',
    'feat.tools.title': 'Batteries-included tooling',
    'feat.tools.body': 'shell · python · browser · search · RAG · db · web3 · http · ssh… and a lot more.',
    'feat.labs.title': 'Multi-agent labs',
    'feat.labs.body': 'Orchestrator + specialist agents collaborate inside persistent labs.',
    'feat.io.title': 'In/out resources',
    'feat.io.body': 'Drop files in, get artifacts out. Each lab has its own working directory.',
    'feat.strategy.title': 'Strategy prompts',
    'feat.strategy.body': 'Steer every lab with a top-level strategy prompt the orchestrator obeys.',
    'feat.antiloop.title': 'Anti-loop system',
    'feat.antiloop.body': 'Detects semantic and tool-call repetition, recovers automatically.',
    'feat.dispatcher.title': 'GPU dispatcher',
    'feat.dispatcher.body': 'Auto-discovers agents, routes models to the right GPU, hot-swaps loads.',
    'feat.sandbox.title': 'Sandboxed execution',
    'feat.sandbox.body': 'Per-lab containers with real process boundaries and command allow-lists.',
    'feat.json.title': 'JSON import/export',
    'feat.json.body': 'Author labs in the UI or as a JSON file — versionable, shareable, diffable.',
    'feat.schedule.title': 'Pause / resume / schedule',
    'feat.schedule.body': 'Long-running jobs survive restarts. Cron labs and human-in-the-loop pauses.',
    'feat.bus.title': 'Real-time event bus',
    'feat.bus.body': 'Live websocket feed of every agent decision, tool call, and message.',
    'feat.unlimited.title': 'No artificial limits',
    'feat.unlimited.body': 'Unlimited labs, agents, providers, tools. Your hardware is the only ceiling.',
  },
  fr: {
    // Header / nav
    'nav.brand': 'Bob Labs',
    'nav.product': 'Produit',
    'nav.platform': 'Plateforme',
    'nav.features': 'Fonctionnalités',
    'nav.deploy': 'Déploiement',
    'nav.pricing': 'Tarifs',
    'nav.docs': 'Docs',
    'nav.blog': 'Blog',
    'nav.live': 'Live',
    'nav.showroom': 'Showroom',
    'nav.signin': 'Connexion',
    'nav.requestTrial': 'Demander un essai',

    // Hero
    'hero.badge': 'Open Source · Auto-hébergé · Agents IA full-stack',
    'hero.title.before': 'La plateforme',
    'hero.title.gradient': "d'agents IA full-stack",
    'hero.title.after': 'qui manquait à votre infrastructure',
    'hero.sub': "Bob Labs exécute des labs multi-agents, du RAG privé, des pipelines GPU et un runtime d'outils sandboxé — sur vos propres serveurs, en deux commandes. Configurez tout visuellement, ou livrez votre lab sous forme de fichier JSON.",
    'hero.cta.start': 'Commencer',
    'hero.cta.preview': 'Aperçu du dashboard',
    'hero.cta.github': 'Voir sur GitHub',
    'hero.proof.private': 'Privé par défaut',
    'hero.proof.noMarkup': 'Pas de marge par token',
    'hero.proof.unlimited': 'Labs & agents illimités',
    'hero.proof.deploy': 'Déploiement en 2 commandes',

    // Product preview section
    'preview.overline': 'Le Produit',
    'preview.title': 'Visite guidée de Bob Labs',
    'preview.lead': "Captures d'écran réelles d'un déploiement en production. Cliquez sur un onglet pour explorer.",

    // Core platform
    'core.overline': 'Plateforme',
    'core.title.line1': "La couche d'infrastructure",
    'core.title.line2': 'qui manque à vos agents IA',

    // Features grid
    'features.overline': 'Tout est inclus',
    'features.title': 'Toutes les briques. Aucun verrouillage.',
    'features.lead': "Privé ou entreprise. Local ou API. Visuel ou JSON. Vous choisissez chaque dimension.",

    // Deploy section
    'deploy.overline': 'Déploiement',
    'deploy.title.before': 'De',
    'deploy.title.after': 'à plateforme en marche — en deux commandes.',
    'deploy.lead': "Pas de Kubernetes, pas de SaaS, pas de file d'attente. Juste Docker Compose sur votre serveur.",
    'deploy.copy.title': 'Deux commandes. Votre stack. Vos données.',
    'deploy.copy.b1.strong': 'Un seul repo',
    'deploy.copy.b1.body': '— toute la plateforme, frontend + backend + services GPU.',
    'deploy.copy.b2.strong': 'Un seul compose',
    'deploy.copy.b2.body': '— activez les modules voulus, laissez le reste de côté.',
    'deploy.copy.b3.strong': 'Zéro appel externe',
    'deploy.copy.b3.body': '— fonctionne entièrement hors ligne si tous vos modèles sont locaux.',
    'deploy.copy.b4.strong': 'Configuration versionnée',
    'deploy.copy.b4.body': '— labs en JSON, prompts dans git, prêt pour audit.',
    'deploy.cta.docs': "Lire le guide d'installation",
    'deploy.cta.github': 'Voir sur GitHub',

    // Private vs Enterprise
    'split.overline': 'Conçu pour les deux',
    'split.title': "Utilisateur privé ou équipe entreprise — même plateforme.",
    'split.private.title': 'Pour usage privé',
    'split.private.b1': 'Tournez-le sur votre serveur perso ou workstation',
    'split.private.b2': 'Mélangez modèles Ollama locaux et fournisseurs API',
    'split.private.b3': 'Conservez documents et conversations sur votre disque',
    'split.private.b4': 'Écrivez vos labs en JSON, partagez-les sur GitHub',
    'split.enterprise.title': 'Pour entreprise',
    'split.enterprise.b1': "Auth JWT, RBAC, panneau d'admin, audit trail",
    'split.enterprise.b2': 'Partagez des labs entre équipes avec contrôle fin',
    'split.enterprise.b3': 'Déployez on-premise ou dans votre VPC',
    'split.enterprise.b4': 'Pilote, production et support SLA sur devis',

    // Pricing
    'pricing.overline': 'Tarifs',
    'pricing.title': 'Tarification simple. Pas de marge par token.',
    'pricing.openSource.title': 'Open Source',
    'pricing.openSource.price': 'Gratuit',
    'pricing.openSource.body': 'Plateforme complète, auto-hébergée, sans restrictions.',
    'pricing.openSource.cta': 'Commencer',
    'pricing.pilot.title': 'Pilote Privé',
    'pricing.pilot.body': "Déploiement initial, premier workflow, cadrage et onboarding.",
    'pricing.production.title': 'Production',
    'pricing.production.body': "Déploiement complet avec audit sécurité, intégrations et accompagnement go-live.",
    'pricing.support.title': 'Support Enterprise',
    'pricing.support.body': "SLA, upgrades, conseil architecture et revues trimestrielles.",
    'pricing.custom': 'Sur devis',
    'pricing.cta.quote': 'Demander un devis',

    // CTA + footer
    'cta.title': 'Vos serveurs. Vos données. Vos agents.',
    'cta.body': "Faites tourner la plateforme IA full-stack sur l'infrastructure que vous maîtrisez déjà. Nous vous accompagnons pour un déploiement managé, sur vos propres serveurs ou hébergé chez nous.",
    'cta.docs': 'Lire la documentation',
    'cta.trial': 'Demander un essai',

    'footer.tagline': "Plateforme d'agents IA full-stack. Open source.",
    'footer.product.title': 'Produit',
    'footer.product.tour': 'Visite',
    'footer.product.core': 'Plateforme',
    'footer.product.features': 'Fonctionnalités',
    'footer.product.pricing': 'Tarifs',
    'footer.resources.title': 'Ressources',
    'footer.resources.docs': 'Documentation',
    'footer.resources.github': 'GitHub',
    'footer.resources.blog': 'Blog',
    'footer.company.title': 'Société',
    'footer.company.contact': 'Contact',
    'footer.company.trial': 'Demander un essai',
    'footer.copyright': '© {year} Bob Labs. Logiciel open source sous licence Apache 2.0.',

    // Quote modal
    'quote.title': 'Demander un devis',
    'quote.intro': "Décrivez votre projet et nous préparerons une proposition adaptée.",
    'quote.success.title': 'Demande envoyée',
    'quote.success.body': "Merci ! Nous reviendrons vers vous rapidement.",
    'quote.close': 'Fermer',
    'quote.field.name': 'Nom complet *',
    'quote.field.email': 'Email professionnel *',
    'quote.field.company': 'Entreprise / Organisation',
    'quote.field.phone': 'Numéro de téléphone',
    'quote.field.description': 'Décrivez vos besoins et votre cas d\'usage',
    'quote.error.required': 'Le nom et l\'email sont requis.',
    'quote.error.generic': 'Une erreur est survenue. Veuillez réessayer.',
    'quote.submit': 'Envoyer la demande',
    'quote.submit.loading': 'Envoi…',

    // Plan labels
    'plan.privatePilot': 'Pilote Privé',
    'plan.production': 'Production',
    'plan.enterpriseSupport': 'Support Enterprise',

    // Trial request page
    'trial.title': "Demander un accès d'essai",
    'trial.intro': "Présentez-vous et nous mettrons en place un workspace d'essai.",
    'trial.success.title': 'Demande envoyée',
    'trial.success.body': "Merci ! Nous reviendrons vers vous rapidement.",
    'trial.success.back': "Retour à l'accueil",
    'trial.field.name': 'Nom complet *',
    'trial.field.email': 'Email professionnel *',
    'trial.field.company': 'Entreprise / Organisation',
    'trial.field.role': 'Votre rôle',
    'trial.field.purpose': 'À quoi comptez-vous utiliser Bob Labs ?',
    'trial.error.required': "Le nom et l'email sont requis.",
    'trial.error.generic': 'Une erreur est survenue. Veuillez réessayer.',
    'trial.submit': 'Envoyer la demande',
    'trial.submit.loading': 'Envoi…',
    'trial.haveToken': 'Vous avez déjà un token ?',
    'trial.signIn': 'Se connecter',

    // Login page
    'login.title': 'Connexion à votre workspace',
    'login.intro': "Entrez le token d'accès fourni par votre administrateur.",
    'login.placeholder': 'bob_xxxxxxxxxxxxxxxx',
    'login.error': "Token d'accès invalide ou expiré.",
    'login.submit': 'Se connecter',
    'login.submit.loading': 'Validation…',
    'login.noToken': "Pas de token ?",
    'login.requestTrial': "Demander un accès d'essai",

    // Docs page chrome
    'docs.title': 'Documentation',
    'docs.search': 'Rechercher…',
    'docs.loading': 'Chargement…',
    'docs.error': 'Échec du chargement du document.',
    'docs.notice.lang': "La documentation est disponible en anglais. L'interface est traduite.",

    // Preview tabs
    'preview.tab.dashboard': 'Dashboard des Labs',
    'preview.tab.lab': "À l'intérieur d'un Lab",
    'preview.tab.lab2': 'Lab — vue agent',
    'preview.tab.agent': "Templates d'agents",
    'preview.tab.memories': 'Mémoires (partageables dans un lab)',
    'preview.tab.models': "Flux d'inférence",
    'preview.tab.stats': "Statistiques d'inférence",
    'preview.tab.dispatch_live': 'Load balancer',
    'preview.tab.live': 'Vue Live',
    'preview.tab.live_attach': 'Live · vue des sorties',

    // Core categories
    'core.enterprise.title': 'Niveau Entreprise',
    'core.enterprise.sub': "Auth, RBAC, partage, panneau d'admin",
    'core.enterprise.b1': "Authentification (JWT) · panneau d'admin · audit trail",
    'core.enterprise.b2': 'Partage de labs entre équipes avec contrôle fin',
    'core.enterprise.b3': "Demandes de devis, onboarding d'essai, niveaux de support",
    'core.data.title': 'Souveraineté des Données',
    'core.data.sub': 'Contrôle total. Confidentialité totale. Vos données, toujours.',
    'core.data.b1': 'PostgreSQL auto-hébergé · RAG vectoriel · graphe LightRAG',
    'core.data.b2': 'Aucune donnée ne sort de votre périmètre',
    'core.data.b3': "Isolation par lab · contrôle d'accès par collection",
    'core.agents.title': 'Agents Sans Limites',
    'core.agents.sub': 'Local ou API · mémoire · outils · tout est paramétrable',
    'core.agents.b1': 'Fournisseurs API (OpenAI, Anthropic, …) et locaux (Ollama, vLLM)',
    'core.agents.b2': "Mémoire persistante · historique complet",
    'core.agents.b3': "Outils : shell, python, browser, search, RAG, db, web3 — et bien plus",
    'core.labs.title': 'Labs & Orchestration',
    'core.labs.sub': "Orchestrateur · agents · ressources · anti-boucle",
    'core.labs.b1': "L'orchestrateur coordonne des agents spécialistes sur des plans multi-étapes",
    'core.labs.b2': "Prompts de stratégie par lab · ressources fichiers in/out",
    'core.labs.b3': "Le système anti-boucle détecte les répétitions et se rétablit seul",
    'core.labs.b4': "Labs, agents et fournisseurs illimités",
    'core.hardware.title': 'Hardware & Dispatch',
    'core.hardware.sub': "Dispatcher GPU · auto-discovery · hot-swap",
    'core.hardware.b1': "Auto-discovery des agents sur plusieurs machines",
    'core.hardware.b2': "Dispatcher intelligent routant les modèles vers le bon GPU",
    'core.hardware.b3': "Pause/reprise des jobs longs · file partagée entre hôtes",
    'core.config.title': 'Entièrement Configurable',
    'core.config.sub': "Chaque prompt, modèle, agent, outil — à façonner",
    'core.config.b1': "Configurez visuellement dans l'UI… ou importez / exportez en JSON",
    'core.config.b2': "Écrivez votre lab entier dans un fichier JSON et livrez-le",
    'core.config.b3': "Surchargez n'importe quel prompt, modèle ou outil",

    // Features grid
    'feat.auth.title': 'Auth & admin utilisateur',
    'feat.auth.body': "Auth JWT, contrôle d'accès, panneau d'admin, audit trail, partage de labs.",
    'feat.private.title': 'Privé par défaut',
    'feat.private.body': "PostgreSQL auto-hébergé, RAG vectoriel, LightRAG. Rien ne sort de votre réseau.",
    'feat.models.title': 'Tout modèle, tout fournisseur',
    'feat.models.body': 'OpenAI, Anthropic, Ollama, vLLM, HF — local + API avec auto-fallback.',
    'feat.memory.title': 'Mémoire & historique',
    'feat.memory.body': "Mémoire persistante par agent et historique complet des conversations.",
    'feat.tools.title': 'Outillage complet',
    'feat.tools.body': 'shell · python · browser · search · RAG · db · web3 · http · ssh… et bien plus.',
    'feat.labs.title': 'Labs multi-agents',
    'feat.labs.body': "Orchestrateur + agents spécialistes collaborent dans des labs persistants.",
    'feat.io.title': 'Ressources in/out',
    'feat.io.body': "Déposez des fichiers, récupérez des artefacts. Chaque lab a son répertoire.",
    'feat.strategy.title': 'Prompts de stratégie',
    'feat.strategy.body': "Pilotez chaque lab via un prompt de stratégie que l'orchestrateur respecte.",
    'feat.antiloop.title': 'Système anti-boucle',
    'feat.antiloop.body': "Détecte les répétitions sémantiques et de tool-calls, se rétablit seul.",
    'feat.dispatcher.title': 'Dispatcher GPU',
    'feat.dispatcher.body': "Auto-discovery des agents, routage des modèles vers le bon GPU.",
    'feat.sandbox.title': 'Exécution sandboxée',
    'feat.sandbox.body': "Conteneurs par lab avec vraies frontières processus et allow-lists.",
    'feat.json.title': 'Import/export JSON',
    'feat.json.body': "Créez vos labs dans l'UI ou en JSON — versionnables, partageables, diffables.",
    'feat.schedule.title': 'Pause / reprise / planification',
    'feat.schedule.body': "Les jobs longs survivent aux redémarrages. Cron labs et pauses humaines.",
    'feat.bus.title': "Bus d'événements temps réel",
    'feat.bus.body': "Flux websocket live de chaque décision, tool call et message d'agent.",
    'feat.unlimited.title': 'Aucune limite artificielle',
    'feat.unlimited.body': "Labs, agents, fournisseurs et outils illimités. Votre hardware fixe la limite.",
  },
};

const I18nContext = createContext({ lang: DEFAULT_LANG, setLang: () => {}, t: (k) => k });

export function I18nProvider({ children }) {
  const [lang, setLangState] = useState(detectInitial);

  useEffect(() => {
    try { window.localStorage.setItem(STORAGE_KEY, lang); } catch { /* ignore */ }
    try { document.documentElement.lang = lang; } catch { /* ignore */ }
  }, [lang]);

  const setLang = useCallback((next) => {
    if (SUPPORTED.includes(next)) setLangState(next);
  }, []);

  const t = useCallback((key, vars) => {
    const dict = messages[lang] || messages[DEFAULT_LANG];
    let str = dict[key];
    if (str === undefined) {
      str = (messages[DEFAULT_LANG] || {})[key];
      if (str === undefined) return key;
    }
    if (vars) {
      for (const [k, v] of Object.entries(vars)) {
        str = str.replace(new RegExp(`\\{${k}\\}`, 'g'), String(v));
      }
    }
    return str;
  }, [lang]);

  const value = useMemo(() => ({ lang, setLang, t, supported: SUPPORTED }), [lang, setLang, t]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useT() {
  return useContext(I18nContext);
}

export function LanguageToggle({ className = '' }) {
  const { lang, setLang } = useT();
  return (
    <div className={`lp-lang-toggle ${className}`} role="group" aria-label="Language selector">
      {SUPPORTED.map((code) => (
        <button
          key={code}
          type="button"
          onClick={() => setLang(code)}
          className={lang === code ? 'is-active' : ''}
          aria-pressed={lang === code}
        >
          {code.toUpperCase()}
        </button>
      ))}
    </div>
  );
}
