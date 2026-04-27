# Trustee MCP Server

An MCP (Model Context Protocol) server that provides AI-powered tools for managing, configuring, and troubleshooting Trustee operator deployments in Kubernetes and OpenShift clusters.

## Purpose

This MCP server enables AI assistants (like Claude) to interact with confidential computing infrastructure, specifically the Trustee operator for managing attestation and Key Broker Service (KBS) in TEE (Trusted Execution Environment) enabled clusters. It automates complex tasks like:

- Cluster configuration detection (platform, TEE type, OCP version)
- Generating reference values for attestation (TDX/SNP on Azure/Baremetal)
- Managing TrusteeConfig resources with security profiles
- Extracting and analyzing attestation tokens
- Certificate and secret management
- Resource inspection and troubleshooting

## Features

### Cluster Detection
- Auto-detect platform type (Azure or Baremetal)
- Auto-detect TEE technology (Intel TDX or AMD SNP)
- Auto-detect OpenShift/OCP version

### Reference Value Generation
- Generate attestation reference values using Veritas
- Support for all combinations: Azure/Baremetal × TDX/SNP
- Automatic cluster configuration detection
- Integration with container registries for image measurement

### Resource Management
- Create and delete TrusteeConfig resources
- Support for permissive and restrictive security profiles
- Automatic certificate and secret generation for restrictive mode
- ConfigMap management for KBS configuration and policies

### Attestation Analysis
- Extract attestation tokens from running pods
- Decode and summarize JWT attestation tokens
- Display trustworthiness vectors and platform details
- Show init data claims and SNP measurements

### Certificate Management
- Generate HTTPS keypairs with OpenShift route SANs
- Generate EC keypairs for attestation token signing
- Create Kubernetes secrets for TLS

### Troubleshooting
- List all Trustee resources in the cluster
- Fetch operator logs
- Read manifest templates
- Get HTTPS certificates from secrets
- Retrieve Trustee URL from routes

## Installation

### Prerequisites
- Python 3.14+
- Access to a Kubernetes/OpenShift cluster with `kubectl`/`oc` configured
- Trustee operator repository (cloned locally)
- Veritas tool repository (cloned locally)

### Clone Required Repositories

```bash
# Clone the trustee-operator repository
git clone https://github.com/confidential-containers/trustee-operator.git ~/git/trustee-operator

# Clone the veritas repository
git clone https://github.com/confidential-containers/veritas.git ~/git/veritas
```

### Install Dependencies

```bash
# Using pip
pip install mcp kubernetes pyyaml veritas

# Or using uv
uv sync
```

### Configure Paths

Copy the example environment file and adjust paths if needed:

```bash
cp .env.example .env
# Edit .env to set custom paths if your repositories are in different locations
```

The server uses the following environment variables with defaults:
- `TRUSTEE_REPO_PATH` - Path to trustee-operator repository (default: `~/git/trustee-operator`)
- `VERITAS_REPO_PATH` - Path to veritas repository (default: `~/git/veritas`)

If your repositories are in the default locations, no configuration is needed.

### Running the Server

```bash
# Using uvx
uvx trustee-mcp-server

# Or with Python
python server.py
```

## Configuration

### Environment Variables

The server can be configured using environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `TRUSTEE_REPO_PATH` | Path to trustee-operator repository | `~/git/trustee-operator` |
| `VERITAS_REPO_PATH` | Path to veritas repository | `~/git/veritas` |

You can set these in a `.env` file (copy from `.env.example`) or export them in your shell:

```bash
export TRUSTEE_REPO_PATH=/path/to/trustee-operator
export VERITAS_REPO_PATH=/path/to/veritas
```

## Available Tools

### Cluster Detection
- `detect_platform()` - Detect if cluster is Azure or Baremetal
- `detect_tee()` - Detect TEE type (TDX or SNP)
- `detect_ocp_version()` - Get OpenShift version
- `detect_cluster_config()` - Detect all configuration at once

### Reference Values
- `generate_reference_values()` - Generate with auto-detection
- `generate_baremetal_tdx_values()` - Baremetal TDX reference values
- `generate_baremetal_snp_values()` - Baremetal SNP reference values
- `generate_azure_tdx_values()` - Azure TDX reference values
- `generate_azure_snp_values()` - Azure SNP reference values
- `update_reference_values_configmap()` - Sync to operator ConfigMap

### TrusteeConfig Management
- `create_trustee_config()` - Create with permissive/restrictive profile
- `delete_trustee_config()` - Delete TrusteeConfig and associated resources

### Certificate & Secret Management
- `generate_https_keypair()` - Generate RSA key/cert for HTTPS
- `generate_attestation_token_keypair()` - Generate EC key/cert for tokens
- `download_pull_secret()` - Download cluster pull secret

### Attestation
- `get_attestation_token()` - Get raw JWT token from pod
- `summarize_attestation_token()` - Decode and summarize token
- `generate_initdata()` - Generate initdata.toml from template
- `generate_test_pod()` - Generate test pod YAML with initdata

### Resource Inspection
- `list_trustee_resources()` - List all Trustee resources
- `get_operator_logs()` - Fetch operator pod logs
- `get_https_certs()` - Get HTTPS certificate from secret
- `get_trustee_url()` - Get KBS route URL
- `read_manifest()` - Read template files

## Example Usage

When connected to an MCP client (like Claude), you can ask questions like:

- "What platform and TEE type is this cluster running?"
- "Generate reference values for this cluster"
- "Create a restrictive TrusteeConfig"
- "Show me the attestation token from the test pod"
- "What's the Trustee URL for this cluster?"

## Security Profiles

### Permissive Profile
- Uses default certificates generated by the operator
- Suitable for development and testing
- Simpler setup with fewer resources

### Restrictive Profile
- Generates custom HTTPS and token signing certificates
- Creates Kubernetes secrets for TLS
- Enhanced security for production environments
- Includes certificate verification for attestation tokens

## Dependencies

- `mcp` - Model Context Protocol framework
- `kubernetes` - Kubernetes Python client
- `pyyaml` - YAML parsing for ConfigMaps
- `veritas` - Reference value generation tool

## Architecture

The server is built using FastMCP and provides tools that execute `kubectl`/`oc` commands to interact with the cluster. It bridges the gap between AI assistants and Kubernetes/confidential computing infrastructure, enabling natural language interactions with complex attestation workflows.

## Contributing

Contributions are welcome! Please ensure your changes maintain compatibility with the Trustee operator and Veritas tool.

## License

See LICENSE file for details.
