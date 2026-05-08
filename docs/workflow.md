# Running Country-Level Scenarios in OSeMOSYS Global

## Introduction

This document explains the workflow used to run country-level scenarios in the OSeMOSYS Global model.

Each country is run separately because different countries require different modelling assumptions. These assumptions are controlled through the configuration file, which acts as the main settings file for the model.

The configuration file tells the model:

- which country to run,
- which years to model,
- which technologies can or cannot be built,
- storage and transmission assumptions,
- emissions limits,
- and which solver to use.

For this exercise, the workflow is completed manually for each country scenario.

---

## Step 1: Clear the Working Environment

Before starting, ensure that the working environment is clean and that previous outputs or unnecessary files have been removed where needed.

---

## Step 2: Activate the OSeMOSYS Global Environment

Activate the modelling environment:

```bash
conda activate OSeMOSYS_Global
```

This loads the required packages and dependencies needed to run the model.

---

## Step 3: Check Out the Exercise Branch

Switch to the branch used for this exercise:

```bash
git checkout issue-253
```

This branch contains the required files and workflow updates.

---

## Step 4: Edit the Configuration File

Open the configuration file and update the assumptions for the country being analysed.

The configuration file acts as the control panel for the model. It contains the main assumptions used during the model run.

Typical changes include:

- updating the country being modelled,
- excluding technologies that are not suitable for a country,
- adjusting emissions assumptions,
- and enabling or disabling storage and transmission options.

For example:

- countries with little or no hydropower potential may exclude hydropower technologies,
- countries without gas infrastructure may exclude CCGT or OCGT technologies,
- and other technologies can also be restricted depending on the country scenario.

These changes are currently made manually for each country scenario.

---

## Step 5: Generate Input Data

Once the configuration file has been updated, generate the model input data using:

```bash
snakemake generate_input_data -j6
```

This step prepares the datasets required for the model run.

The `-j6` option allows Snakemake to run six jobs in parallel, which helps reduce processing time.

---

## Step 6: Update Demand Data

Where necessary, replace or update the electricity demand input data before running the full workflow.

This ensures that the demand assumptions match the country and scenario being analysed.

---

## Step 7: Run the Model Workflow

Run the workflow to execute the model and generate outputs:

```bash
snakemake -j6
```

This step solves the model and produces the standard OSeMOSYS outputs.

---

## Step 8: Review Result Summaries

Once the workflow has completed successfully, review the outputs located in the `result_summaries` folder.

For this exercise, the main output of interest is:

### Discounted Cost of Electricity

This represents the total discounted whole-system cost of supplying electricity within the scenario and is the main metric used to compare scenarios across countries.

The analysis also includes:

### Average Annual Emission Intensity

This value is calculated by averaging the annual electricity emission intensity across the modelling period. It is used to compare the carbon intensity of electricity generation between scenarios.

A final metric used in the analysis is:

### Capital Investment to New Capacity Ratio

This metric is calculated using the following outputs:

- `CapitalInvestment.csv`
- `NewCapacity.csv`

The ratio is calculated by dividing total annual capital investment by total annual new generation capacity added to the system.

This provides an estimate of the average investment cost associated with building new electricity generation infrastructure.

The ratio is calculated for each year and then averaged across the modelling period to create a single summary value for comparison across scenarios.

---

## Key Metrics Used in the Analysis

The analysis focuses on three main outputs:

- **Discounted Cost of Electricity** (whole-system cost),
- **Average Annual Emission Intensity**, and
- **Average Capital Investment to New Capacity Ratio**.

These metrics are used together to compare the economic and environmental performance of each country scenario.  