# AgentSociety Benchmark Toolkit

## Tool Objectives

The AgentSociety Benchmark Toolkit is a comprehensive evaluation tool designed for multi-agent systems. This tool aims to help researchers and developers:

- **Standardize Evaluation Process**: Provide a unified evaluation framework to ensure fair comparison between different agent systems
- **Multi-Scenario Testing**: Support agent behavior evaluation in various real-world scenarios
- **Automated Assessment**: Simplify the entire evaluation workflow from data preparation to result analysis
- **Reproducibility**: Ensure reproducibility and verifiability of experimental results

## Supported Benchmarks

### 1. BehaviorModeling
The BehaviorModeling benchmark focuses on evaluating agents' behavior modeling capabilities in complex social scenarios. This benchmark tests how agents:
- Understand and simulate human behavior patterns
- Make reasonable decisions in group environments
- Adapt to different social norms and constraints

### 2. DailyMobility
The DailyMobility benchmark evaluates agents' mobility behavior modeling capabilities in daily life. This benchmark tests how agents:
- Plan reasonable daily activity routes
- Consider correlations between time, location, and activities
- Simulate real-world mobility patterns

### 3. HurricaneMobility
The HurricaneMobility benchmark focuses on evaluating agents' behavior modeling capabilities in emergency situations. This benchmark tests how agents:
- Make emergency decisions during natural disasters
- Simulate crowd evacuation and shelter-seeking behaviors
- Handle uncertainty and resource allocation in emergency situations

## Basic Usage

### Installation

```bash
# Install from source
git clone <repository-url>
cd packages/agentsociety-benchmark
pip install -e .

# Or install via pip (if published)
pip install agentsociety-benchmark
```

### Command Line Interface

#### View Available Tasks

```bash
# List all available benchmark tasks
asbench list-tasks
```

#### Download Datasets
- You need to install git lfc firstly.
```bash
# Clone datasets for specific benchmarks, this will clone the datasets and install dependancies at the same time
asbench clone BehaviorModeling
asbench clone DailyMobility
asbench clone HurricaneMobility

# View installed benchmarks
asbench list-installed

# Force clone datasets for specific benchmarks
asbench clone BehaviorModeling --force

# Only install dependancies for specific benchmarks
asbench clone BehaviorModeling --only-install-deps
```

#### Run Evaluation

```bash
# Run evaluation for specific benchmark
asbench run <TASK-NAME> --config your_config.yaml --agent your_agent.py --mode test/inference
```

#### Independent Result Evaluation

```bash
# Independently evaluate generated result files
asbench evaluate <TASK-NAME> results.json --config your_config.yaml
```

#### Update Benchmarks

```bash
# Update all benchmarks to latest versions
asbench update-benchmarks
```

### Programmatic Usage

The AgentSociety Benchmark also supports programmatic usage through Python code, allowing you to integrate benchmark execution into your applications and scripts.

#### Basic Usage

```python
import asyncio
from agentsociety_benchmark import BenchmarkRunner, run_benchmark, evaluate_results

async def run_my_benchmark():
    # Create a BenchmarkRunner instance
    runner = BenchmarkRunner(home_dir="./benchmark_data")
    
    # Run a benchmark
    result = await runner.run_benchmark(
        task_name="BehaviorModeling",
        benchmark_config="config.yaml",
        agent_config="agent_config.yaml",
        mode="test",  # Run with evaluation
        tenant_id="my_tenant",
        exp_id="my_experiment_001"
    )
    
    print(f"Benchmark completed! Experiment ID: {result['exp_id']}")
    print(f"Results: {result['results']}")
    print(f"Evaluation: {result['evaluation']}")

# Run the benchmark
asyncio.run(run_my_benchmark())
```

#### Using Convenience Functions

```python
import asyncio
from agentsociety_benchmark import run_benchmark, evaluate_results, list_available_tasks

async def simple_benchmark():
    # List available tasks
    tasks = list_available_tasks()
    print(f"Available tasks: {tasks}")
    
    # Run benchmark using convenience function
    result = await run_benchmark(
        task_name="BehaviorModeling",
        benchmark_config="config.yaml",
        agent_config="agent_config.yaml",
        mode="inference"  # Run without evaluation
    )
    
    # Evaluate results separately if needed
    if result['results']:
        evaluation = await evaluate_results(
            task_name="BehaviorModeling",
            results_file="results.pkl",
            benchmark_config="config.yaml"
        )
        print(f"Evaluation result: {evaluation['evaluation_result']}")

asyncio.run(simple_benchmark())
```

#### Advanced Usage

```python
import asyncio
from agentsociety_benchmark import BenchmarkRunner

async def advanced_benchmark():
    # Create runner with custom settings
    runner = BenchmarkRunner(home_dir="./custom_data")
    
    # Run with advanced configuration
    result = await runner.run_benchmark(
        task_name="BehaviorModeling",
        benchmark_config="my_config.yaml",
        agent_config="my_agent.py",
        datasets_path="./my_datasets",
        mode="test",
        tenant_id="advanced_example",
        exp_id="advanced_001",
        official=True,  # Mark as official validation
        callback_url="https://my-callback-url.com/webhook"
    )
    
    print(f"Advanced benchmark completed: {result}")

asyncio.run(advanced_benchmark())
```

#### Configuration Files

You'll need to create configuration files for your benchmarks:

**Benchmark Configuration (config.yaml):**
```yaml
llm:
- api_key: YOUR-API-KEY
  model: gpt-4
  provider: openai
  semaphore: 200
env:
  db:
    enabled: true
  home_dir: .agentsociety-benchmark/agentsociety_data
```

**Agent Configuration (agent_config.yaml):**
```yaml
agent_class: my_agent.py
number: 1
config:
  name: MyAgent
  description: A custom agent for testing
```

#### Complete Example

See `examples/programmatic_usage.py` for a complete working example that demonstrates all the features of the programmatic API.

### Storage and Configuration

- **Data Storage**: All benchmark data is stored in the `.agentsociety-benchmark/` directory
- **Configuration Files**: Use YAML format configuration files to define agent parameters and evaluation settings
- **Result Storage**: Evaluation results are saved in JSON format for easy subsequent analysis and comparison

## Configuration Example

```yaml
# config.yaml
llm:
- api_key: YOUR-API-KEY # LLM API key
  model: YOUR-MODEL # LLM model
  provider: PROVIDER # LLM provider
  semaphore: 200 # Semaphore for LLM requests, control the max number of concurrent requests
env:
  db:
    enabled: true # Whether to enable database
  home_dir: .agentsociety-benchmark/agentsociety_data
```

## Requirements

- Python >= 3.11
- agentsociety >= 1.5.0a11
- Other dependencies see `pyproject.toml`

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.