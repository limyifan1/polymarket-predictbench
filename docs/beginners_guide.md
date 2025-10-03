# Beginner's Guide to the PredictBench Pipeline

This guide provides a comprehensive overview of the data flow and database schema for the Polymarket PredictBench application. It's intended for new developers who want to understand how the system works from end to end.

## The Big Picture: Data Flow

The application's core purpose is to fetch prediction market data, run experiments (which involve research and forecasting), and store the results. The data flows through the system in three main stages:

1.  **Ingestion:** Raw data about prediction markets is fetched from an external source (Polymarket). This data is then cleaned and "normalized" into a standard format. The normalized data is then stored in our database.

2.  **Processing:** Before we run any experiments, we create a "snapshot" of the market data. This ensures that our experiments are reproducible and that the data doesn't change halfway through a run. This snapshot is tied to a specific `processing_run`.

3.  **Experimentation:** This is where the magic happens. An "experiment" consists of two stages:
    *   **Research:** In this stage, we gather information that might be useful for making a prediction. For example, we might use an AI model to search the web for relevant news articles and generate a summary. The output of this stage is a "research artifact".
    *   **Forecasting:** In this stage, we make a prediction for a given market. This prediction can be based on the information gathered in the research stage. For example, an AI model might take the research summary and generate a forecast. The output of this stage is an "experiment result".

## Deep Dive: The Database Tables

The database is the backbone of the application. The tables can be grouped into three categories:

### Core Tables

These tables store the primary data about markets, contracts, and events.

*   `markets`: This is the central table, containing information about each prediction market, such as its question (`"Will Donald Trump win the 2024 US Presidential Election?"`), category, and status.
*   `contracts`: Each market has one or more "contracts", which represent the possible outcomes. For example, a market might have two contracts: "Yes" and "No". This table stores information about each contract, including its current price.
*   `events`: Some markets are part of a larger "event". For example, there might be an "US Election 2024" event that contains multiple markets for different outcomes. This table stores information about these events.

### Pipeline Run Tables

These tables store data related to the execution of the data processing pipeline.

*   `processing_runs`: Every time the pipeline runs, a record is created in this table. This allows us to track the history of our pipeline runs and ensures that our data is versioned.
*   `processed_markets`: When a pipeline run executes, it creates a snapshot of each market it's going to process. This snapshot is stored in this table and is linked to the `processing_runs` record. This ensures that the data for a market is consistent throughout a single pipeline run.
*   `processed_contracts`: Similar to `processed_markets`, this table stores a snapshot of the contracts for a processed market.
*   `processed_events`: Similar to `processed_markets`, this table stores a snapshot of the events.
*   `processing_failures`: If something goes wrong during a pipeline run (e.g., we can't fetch data for a market), the error is logged in this table.

### Experiment Tables

These tables store data related to the experiments we run.

*   `experiments`: This table contains a definition for each experiment, including its name and version. This allows us to track different versions of our experiments and compare their results.
*   `experiment_runs`: A record in this table represents a single run of an experiment. It's linked to a `processing_run` (which provides the data) and an `experiment` (which provides the logic).
*   `research_artifacts`: This table stores the output of the "research" stage of an experiment. The `payload` column contains the actual research data (e.g., a text summary from an AI model). It is linked to an `experiment_run` and a `processed_market` or `processed_event`.
*   `experiment_results`: This table stores the output of the "forecast" stage of an experiment. The `payload` column contains the prediction. It is linked to an `experiment_run` and can also be linked to a `research_artifact` that was used to generate the forecast.

## Putting It All Together: An Example Scenario

Let's walk through a simplified example to see how all the pieces fit together.

1.  **Ingestion:** The application ingests a new market from Polymarket: `"Will it rain in New York City tomorrow?"`. A new record is created in the `markets` table. The market has two contracts, "Yes" and "No", which are added to the `contracts` table.

2.  **Pipeline Run:** A new daily pipeline run is triggered. A record is created in `processing_runs`. Our new market is selected for processing, and a snapshot of it is created in the `processed_markets` table.

3.  **Experiment Run:** An experiment named `"weather_forecast_v1"` is set to run. A new record is created in `experiment_runs`, linked to our `processing_run`.

4.  **Research Stage:** The experiment's research stage begins. An AI model is tasked with searching for weather forecasts for NYC. It finds a few and creates a summary. This summary is saved as a `research_artifact`, linked to the `experiment_run` and the `processed_market`.

5.  **Forecast Stage:** The experiment's forecast stage begins. Another AI model takes the research artifact (the weather forecast summary) and generates a prediction: a 70% chance of rain. This prediction is saved as an `experiment_result`, linked to the `experiment_run` and the `research_artifact`.

Now, the `experiment_results` table contains our prediction, and we have a full audit trail of how we got there, from the initial data ingestion to the final forecast.
