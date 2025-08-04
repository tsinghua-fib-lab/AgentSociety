# Start Your First Simulation

Follow the steps below to begin our simulation of societal dynamics for 50 individuals over a period of 1 day in Beijing.

## Step 0: Installation

To install the necessary package, run the following command:

```bash
pip install agentsociety
```

```{admonition} Warning
:class: warning
Please ensure your environment matches the supported platforms shown in the [Prerequisites](./01-prerequisites.md) section.
```

```{admonition} Hint
:class: hint
If you look the error like `ERROR: Could not find a version that satisfies the requirement agentsociety`, it means your OS, architecture or python version is not supported.
Please refer to the [Prerequisites](./01-prerequisites.md) section for more details.
It could also be the Python mirror source problem. In that case, please switch the mirror source and try again.
```

## Step 1: Download City Scene Data

Before the simulation starts, it is necessary to download the city scene data file of [Beijing](https://cloud.tsinghua.edu.cn/f/f5c777485d2748fa8535/?dl=1), and save it as `./data/beijing_map.pb`.

## Step 2: Edit Configurations

We need to create one configuration file, which is assumed to be named `config.yaml`.
An example configuration file is shown below, you can refer to it to create your own configuration file, remember to replace the placeholders with your own values.

``` yaml
llm:
- api_key: <API-KEY> # LLM API key
  base_url: <BASE-URL> # LLM base URL, used for VLLM and Ollama
  model: <YOUR-MODEL> # LLM model
  provider: <PROVIDER> # LLM provider
  semaphore: 200 # Semaphore for LLM requests, control the max number of concurrent requests
env:
  db:
    enabled: true # Whether to enable database
    db_type: sqlite # Database type, currently supported: sqlite (default), postgresql
map:
  file_path: <MAP-FILE-PATH> # Path to the map file
agents:
  citizens:
  - agent_class: citizen # The class of the agent
    number: 100 # The number of the agents
exp:
  name: test # Experiment name
  environment:
    start_tick: 28800 # Start time in seconds
    total_tick: 7200 # Total time in seconds
  workflow:
  - day: 1 # The day of the workflow step
    type: run # The type of the workflow step
```

### Example Configuration for Ollama

If you're using Ollama for local model inference, here's a specific example configuration:

```yaml
llm:
- api_key: "dummy" # Ollama doesn't require a real API key, but field is required
  base_url: "http://localhost:11434/v1" # Default Ollama endpoint (optional, will default to this)
  model: "llama2" # Your downloaded Ollama model
  provider: "ollama" # Set provider to ollama
  semaphore: 200
env:
  db:
    enabled: true
    db_type: sqlite
map:
  file_path: "./data/beijing_map.pb"
agents:
  citizens:
  - agent_class: citizen
    number: 100
exp:
  name: ollama_test
  environment:
    start_tick: 28800
    total_tick: 7200
  workflow:
  - day: 1
    type: run
```

```{admonition} Hint
:class: hint
You can run `agentsociety check -c config.yaml` to check if your own configuration file is valid, which will check the configuration file and give you a detailed error message if there is any problem.
```

## Step 3：Launch the Simulation

1. From Command Line

After editing the configuration file, you can easily run the following command to launch the simulation.
```bash
agentsociety run -c config.yaml
```

2. From Python Code

If you want to launch the simulation from a python script, you can use the following code.

```python
import asyncio
import logging

import ray

from agentsociety.cityagent import default
from agentsociety.configs import Config, load_config_from_file
from agentsociety.simulation import AgentSociety

async def main():
    ray.init(logging_level=logging.INFO)
    config = load_config_from_file(
        filepath="config.yaml",
        config_type=Config,
    )
    config = default(config) # This is necessary when using the default cityagent implementation
    agentsociety = AgentSociety(config)
    await agentsociety.init()
    await agentsociety.run()
    await agentsociety.close()
    ray.shutdown()


if __name__ == "__main__":
    asyncio.run(main())

```

```{admonition} Attention
:class: attention
Please always remember to call the `default` function when using the default cityagent implementation rather than implementing all the agent classes (including citizens, firms, banks, nbs, governments) by yourself.
```

Fill in the placeholders in the configuration file with your own values, and run the code above to start the simulation.



After running the command above, you will see the following output, indicating that the simulation has been successfully launched.
![ExampleStart](../_static/01-exp-start.png)

When the simulation is running, you will see the following output.
![ExampleRunning](../_static/01-exp-running.png)

After the simulation is finished, you will see the following output.
![ExampleClose](../_static/01-exp-close.png)

```{admonition} Note
:class: note
When the simulation is over, you can see an error `exception asyncio.CancelledError` in the output. This is normal and can be ignored.
```

## Step 4：View the Results

When the simulation is done (or is running), you can use our visualization tool within the python package `agentsociety ui` to replay the simulation.

To activate the ui interface, you simply need to code these in your terminal, the `config.yaml` is just the same file as the one you used to run the simulation.
```bash
agentsociety ui -c config.yaml
```

Running the code above will activate the UI Interface, as shown below.

![start-ui](../_static/01-start-ui.png)

![home-page](../_static/01-ui-home-page.jpg) 

![exp-list](../_static/01-exp-list.jpg)

## Next Step

Congratulations🎇! Now that we have successfully completed a large model-driven social simulation, let's take it a step further and explore how to modify certain settings in the virtual world to [conduct social experiments](./03-conduct-your-first-experiment.md).
