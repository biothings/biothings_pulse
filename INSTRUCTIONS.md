# BioThings Pulse — Project Instructions

> This file captures the original project brief for future reference. Do not delete.

## Background

A BioThings API typically starts with a **BioThings Hub** setup to monitor multiple
data sources. Once a new data update is detected, the Hub triggers a pipeline:

1. **dump** — download data files
2. **upload** — run a parser to convert data files into structured objects
3. **build** — merge multiple sources into one data collection (if needed)
4. **release / index** — index the merged collection in Elasticsearch for search

Within a BioThings Hub, each data source is organized as a **data plugin**.
More details: https://docs.biothings.io (relevant sections: **BioThings Hub** and
**Data Plugins**).

## Goal

Create a standalone API server — project name **"biothings pulse"** — that runs
**only the data-source-check step** of a data plugin and returns the status of a
data source. It should minimally return:

1. Is there a new data update?
2. What is the current version?
3. If there is a new update, what is the latest version?
4. *(Optional)* A list of URLs for data downloads, if the data plugin can provide them.

## Supported data plugins

Two plugin types must be supported:

- **Manifest-based data plugins** — typically under the `plugins/` folder of a hub repo.
- **"Advanced" data plugins** — typically under `[src]/hub/dataload/sources/` of a hub repo.

## Existing BioThings Hub repos (under the `biothings` GitHub org)

- mygene.info
- myvariant.info
- mychem.info
- mydisease.info
- biothings.species
- mygeneset.info
- pending.api
- NAR.API

The list of plugins for each hub is under `plugins/` (manifest-based) or
`[src]/hub/dataload/sources/` (advanced).

**Future expansion:** the set of supported data plugins is expected to grow by
adding additional hub repos, or a repo containing only data plugins.

## Deployment

This is a **production-ready API** expected to be deployed to an **AWS environment**.
Create the necessary setup for deployment purposes.

## Process

- Write this instruction into a local file for future reference (this file).
- Make an implementation plan **first**, before writing any code.
