from mcp.server.fastmcp import FastMCP
import subprocess
import os
import base64
import gzip
import json

# Initialize FastMCP Server
mcp = FastMCP("Trustee-Troubleshooter")

TRUSTEE_REPO_PATH = "/home/lmilleri/git/trustee-operator"
VERITAS_REPO_PATH= "/home/lmilleri/git/veritas"

@mcp.tool()
def list_trustee_resources() -> str:
    """List all Trustee resources in the cluster."""
    cmd = "kubectl get all -n trustee-operator-system"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout if result.stdout else result.stderr

@mcp.tool()
def get_operator_logs() -> str:
    """Fetch logs from the trustee-operator pod."""
    cmd = "export POD_NAME=$(kubectl get pods -l app=kbs -o jsonpath='{.items[0].metadata.name}' -n trustee-operator-system) && kubectl logs -n trustee-operator-system $POD_NAME"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout

@mcp.tool()
def read_manifest(filename: str) -> str:
    """Read a manifest file from the trustee-operator config directory."""
    path = os.path.join(TRUSTEE_REPO_PATH, "config/templates", filename)
    with open(path, "r") as f:
        return f.read()

@mcp.tool()
def read_init_data_template() -> str:
    with open("initdata.toml.in", "r") as f:
        return f.read()

@mcp.tool()
def get_https_certs() -> str:
    """Get the HTTPS certificate from the trustee-operator secret."""
    # Try the new combined secret format first
    cmd = "kubectl get secret trusteeconfig-https-secret -n trustee-operator-system -o jsonpath='{.data.tls\\.crt}' | base64 -d"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

    # If that fails, try the old separate cert secret format for backward compatibility
    if result.returncode != 0 or not result.stdout:
        cmd = "kubectl get secret trusteeconfig-https-cert-secret -n trustee-operator-system -o jsonpath='{.data.certificate}' | base64 -d"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

    return result.stdout

@mcp.tool()
def get_trustee_url() -> str:
    """Get the Trustee URL from the OpenShift route."""
    cmd = "oc get route kbs-route -n trustee-operator-system -o jsonpath='{.spec.host}'"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return f"https://{result.stdout}" if result.stdout else ""

@mcp.tool()
def download_pull_secret(output_file: str = "pull-secret.json") -> str:
    """
    Download the pull secret from the OpenShift cluster.

    Args:
        output_file: Path to save the pull secret (default: "pull-secret.json")

    Returns:
        Success message or error message
    """
    cmd = f"oc get secret/pull-secret -n openshift-config -o jsonpath='{{.data.\\.dockerconfigjson}}' | base64 -d > {output_file}"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

    if result.returncode != 0:
        return f"Error: Failed to download pull secret\n{result.stderr}"

    # Verify the file was created and is valid JSON
    try:
        with open(output_file, 'r') as f:
            content = f.read()
            json.loads(content)  # Validate it's valid JSON
        return f"Successfully downloaded pull secret to {output_file}"
    except FileNotFoundError:
        return f"Error: Failed to create {output_file}"
    except json.JSONDecodeError:
        return f"Error: Downloaded content is not valid JSON"
    except Exception as e:
        return f"Error: {e}"

@mcp.tool()
def generate_initdata() -> str:
    """Generate initdata.toml from template by fetching TRUSTEE_URL and TRUSTEE_CERT from the cluster."""
    # Get the Trustee URL and certificate using existing functions
    trustee_url = get_trustee_url()
    trustee_cert = get_https_certs()

    if not trustee_url:
        return "Error: Failed to retrieve Trustee URL from cluster"
    if not trustee_cert:
        return "Error: Failed to retrieve HTTPS certificate from cluster"

    # Read the template
    try:
        with open("initdata.toml.in", "r") as f:
            template = f.read()
    except FileNotFoundError:
        return "Error: initdata.toml.in template file not found"

    # Substitute the values
    output = template.replace('${TRUSTEE_URL}', trustee_url)
    output = output.replace('${TRUSTEE_CERT}', trustee_cert)

    # Write the output
    with open("initdata.toml", "w") as f:
        f.write(output)

    return f"Successfully generated initdata.toml with:\n  URL: {trustee_url}\n  Certificate: {len(trustee_cert)} bytes"

@mcp.tool()
def generate_test_pod() -> str:
    """Generate test-pod.yaml from template by gzipping and base64-encoding initdata.toml."""
    # Read initdata.toml
    try:
        with open("initdata.toml", "r") as f:
            initdata_content = f.read()
    except FileNotFoundError:
        return "Error: initdata.toml not found. Run generate_initdata() first."

    # Gzip and base64 encode the initdata content (equivalent to: cat initdata.toml | gzip | base64 -w0)
    initdata_gzipped = gzip.compress(initdata_content.encode('utf-8'))
    initdata_base64 = base64.b64encode(initdata_gzipped).decode('utf-8')

    # Read the template
    try:
        with open("test-pod.yaml.in", "r") as f:
            template = f.read()
    except FileNotFoundError:
        return "Error: test-pod.yaml.in template file not found"

    # Substitute the INITDATA variable
    output = template.replace('${INITDATA}', initdata_base64)

    # Write the output
    with open("test-pod.yaml", "w") as f:
        f.write(output)

    return f"Successfully generated test-pod.yaml with {len(initdata_base64)} bytes of gzipped+base64-encoded initdata"

@mcp.tool()
def get_attestation_token(pod_name: str = "ocp-cc-pod", token_type: str = "kbs") -> str:
    """
    Get the attestation token from a running pod using the attestation agent API.

    Args:
        pod_name: Name of the pod to query (default: "ocp-cc-pod")
        token_type: Type of token to request (default: "kbs")

    Returns:
        The attestation token or error message

    Note: This requires the pod to have agent.guest_components_rest_api=attestation or =all enabled.
    """
    # Use oc exec to curl the attestation agent API endpoint
    cmd = f'kubectl exec -it {pod_name} -- curl -s "http://127.0.0.1:8006/aa/token?token_type={token_type}"'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

    if result.returncode != 0:
        return f"Error: {result.stderr if result.stderr else 'Failed to execute command'}"

    if not result.stdout:
        return "Error: No output from attestation agent. Ensure the pod has agent.guest_components_rest_api enabled."

    # Check if it's a 404 error
    if "404" in result.stdout or "NOT FOUND" in result.stdout:
        return (
            "Error: Attestation API not available (404). "
            "The pod needs the kernel parameter: agent.guest_components_rest_api=attestation or =all\n"
            "Add this annotation to enable:\n"
            "  io.katacontainers.config.hypervisor.kernel_params: \"agent.guest_components_rest_api=all\""
        )

    return result.stdout

@mcp.tool()
def summarize_attestation_token(pod_name: str = "ocp-cc-pod", token_type: str = "kbs") -> str:
    """
    Get the attestation token and provide a human-readable summary.

    Args:
        pod_name: Name of the pod to query (default: "ocp-cc-pod")
        token_type: Type of token to request (default: "kbs")

    Returns:
        A human-readable summary of the attestation token
    """
    # Get the token using the existing function
    token_response = get_attestation_token(pod_name, token_type)

    # Check for errors
    if token_response.startswith("Error:"):
        return token_response

    try:
        # Parse the JSON response
        token_data = json.loads(token_response)
        jwt_token = token_data.get("token", "")

        if not jwt_token:
            return "Error: No token found in response"

        # Decode JWT (split and decode payload without verification)
        parts = jwt_token.split(".")
        if len(parts) != 3:
            return "Error: Invalid JWT format"

        # Decode the payload (second part)
        # Add padding if needed
        payload = parts[1]
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += "=" * padding

        decoded_payload = base64.urlsafe_b64decode(payload)
        payload_data = json.loads(decoded_payload)

        # Extract key information
        summary = []
        summary.append("=== Attestation Token Summary ===\n")

        # Basic token info
        if "iat" in payload_data:
            from datetime import datetime
            iat = datetime.fromtimestamp(payload_data["iat"])
            summary.append(f"Issued At: {iat.strftime('%Y-%m-%d %H:%M:%S')}")

        if "exp" in payload_data:
            from datetime import datetime
            exp = datetime.fromtimestamp(payload_data["exp"])
            summary.append(f"Expires At: {exp.strftime('%Y-%m-%d %H:%M:%S')}")

        if "eat_profile" in payload_data:
            summary.append(f"EAT Profile: {payload_data['eat_profile']}")

        # Verifier info
        if "ear.verifier-id" in payload_data:
            verifier = payload_data["ear.verifier-id"]
            summary.append(f"\nVerifier:")
            summary.append(f"  Developer: {verifier.get('developer', 'N/A')}")
            summary.append(f"  Build: {verifier.get('build', 'N/A')}")

        # Submods (CPU attestation details)
        if "submods" in payload_data and "cpu0" in payload_data["submods"]:
            cpu0 = payload_data["submods"]["cpu0"]
            summary.append(f"\nCPU Attestation:")
            summary.append(f"  Status: {cpu0.get('ear.status', 'N/A')}")

            if "ear.trustworthiness-vector" in cpu0:
                tv = cpu0["ear.trustworthiness-vector"]
                summary.append(f"  Trustworthiness Vector:")
                summary.append(f"    Instance Identity: {tv.get('instance-identity', 'N/A')}")
                summary.append(f"    Configuration: {tv.get('configuration', 'N/A')}")
                summary.append(f"    Executables: {tv.get('executables', 'N/A')}")
                summary.append(f"    Hardware: {tv.get('hardware', 'N/A')}")

            # Extract init_data claims
            if "ear.veraison.annotated-evidence" in cpu0:
                evidence = cpu0["ear.veraison.annotated-evidence"]

                if "init_data" in evidence:
                    summary.append(f"\n  Init Data Hash: {evidence['init_data'][:32]}...")

                if "init_data_claims" in evidence:
                    claims = evidence["init_data_claims"]

                    # AA config
                    if "aa.toml" in claims and "token_configs" in claims["aa.toml"]:
                        token_configs = claims["aa.toml"]["token_configs"]
                        if "kbs" in token_configs:
                            kbs_url = token_configs["kbs"].get("url", "N/A")
                            summary.append(f"\n  KBS URL: {kbs_url}")

                # SNP measurement
                if "snp" in evidence:
                    snp = evidence["snp"]
                    if "measurement" in snp:
                        summary.append(f"\n  SNP Measurement: {snp['measurement'][:64]}...")

                    summary.append(f"  Platform Details:")
                    summary.append(f"    SMT Enabled: {snp.get('platform_smt_enabled', 'N/A')}")
                    summary.append(f"    TSME Enabled: {snp.get('platform_tsme_enabled', 'N/A')}")
                    summary.append(f"    Debug Allowed: {snp.get('policy_debug_allowed', 'N/A')}")
                    summary.append(f"    TCB Bootloader: {snp.get('reported_tcb_bootloader', 'N/A')}")
                    summary.append(f"    TCB Microcode: {snp.get('reported_tcb_microcode', 'N/A')}")
                    summary.append(f"    TCB SNP: {snp.get('reported_tcb_snp', 'N/A')}")

        # TEE public key info
        if "tee_keypair" in token_data:
            summary.append(f"\n  TEE Keypair: Present (private key included)")

        return "\n".join(summary)

    except json.JSONDecodeError as e:
        return f"Error: Failed to parse JSON response: {e}"
    except Exception as e:
        return f"Error: Failed to process token: {e}"

@mcp.tool()
def generate_reference_values(
    platform: str = None,
    tee: str = None,
    ocp_version: str = None,
    osc_version: str = None,
    authfile: str = None,
    initdata: str = "initdata.toml",
    output_dir: str = ".",
    kernel_cmdline: str = None,
    max_cpu_count: int = None,
    mem_size: int = None,
    hw_xfam_allow: list = None,
    verbose: bool = False
) -> str:
    """
    Generate attestation reference values using veritas.
    Automatically detects platform, TEE, and OCP version if not provided.

    Args:
        platform: Platform type - "azure" or "baremetal" (auto-detected if not provided)
        tee: TEE type - "tdx" or "snp" (auto-detected if not provided)
        ocp_version: OCP version (e.g., "4.20.15", baremetal only, auto-detected if not provided)
        osc_version: OSC dm-verity image tag (azure only)
        authfile: Path to registry auth file (pull-secret.json)
        initdata: Path to initdata.toml file (default: "initdata.toml")
        output_dir: Output directory for generated values (default: current directory)
        kernel_cmdline: Override kernel command line (baremetal only)
        max_cpu_count: Max nr_cpus for cmdline variants (default: 32, baremetal only)
        mem_size: VM memory size in MB (default: 2048, baremetal TDX only)
        hw_xfam_allow: List of XFAM CPU features (TDX only, e.g., ["x87", "sse", "avx"])
        verbose: Enable verbose output

    Returns:
        Success message with output location or error message
    """
    # Track auto-detected values for reporting
    auto_detected = []

    # Auto-detect platform if not provided
    if platform is None:
        platform = detect_platform()
        if platform.startswith("Error"):
            return f"Failed to auto-detect platform: {platform}"
        auto_detected.append(f"platform: {platform}")

    # Auto-detect TEE if not provided
    if tee is None:
        tee = detect_tee()
        if tee.startswith("Error"):
            return f"Failed to auto-detect TEE: {tee}"
        auto_detected.append(f"TEE: {tee}")

    # Auto-detect OCP version for baremetal if not provided
    if platform == "baremetal" and ocp_version is None:
        ocp_version = detect_ocp_version()
        if ocp_version.startswith("Error"):
            return f"Failed to auto-detect OCP version: {ocp_version}"
        auto_detected.append(f"OCP version: {ocp_version}")

    # Validate platform
    if platform not in ["azure", "baremetal"]:
        return "Error: platform must be 'azure' or 'baremetal'"

    if tee not in ["tdx", "snp"]:
        return "Error: tee must be 'tdx' or 'snp'"

    # Build the command
    cmd = [
        "python3", "-m", "veritas",
        "--platform", platform,
        "--tee", tee
    ]

    # Add version parameters
    if ocp_version:
        cmd.extend(["--ocp-version", ocp_version])

    if osc_version:
        cmd.extend(["--osc-version", osc_version])

    # Add authfile if provided
    if authfile:
        cmd.extend(["--authfile", authfile])

    # Add initdata path
    cmd.extend(["--initdata", initdata])

    # Add output directory
    cmd.extend(["-o", output_dir])

    # Add optional parameters
    if kernel_cmdline:
        cmd.extend(["--kernel-cmdline", kernel_cmdline])

    if max_cpu_count is not None:
        cmd.extend(["--max-cpu-count", str(max_cpu_count)])

    if mem_size is not None:
        cmd.extend(["--mem-size", str(mem_size)])

    # Add XFAM features if provided
    if hw_xfam_allow:
        for feature in hw_xfam_allow:
            cmd.extend(["--hw-xfam-allow", feature])

    if verbose:
        cmd.append("-v")

    # Change to veritas directory and run
    try:
        result = subprocess.run(
            cmd,
            cwd=VERITAS_REPO_PATH,
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )

        if result.returncode != 0:
            return f"Error: veritas failed with exit code {result.returncode}\n\nStderr:\n{result.stderr}\n\nStdout:\n{result.stdout}"

        # Return success message with output
        output_msg = [
            f"Successfully generated reference values for {platform}/{tee}",
        ]

        if auto_detected:
            output_msg.append(f"Auto-detected: {', '.join(auto_detected)}")

        if ocp_version:
            output_msg.append(f"OCP version: {ocp_version}")
        if osc_version:
            output_msg.append(f"OSC version: {osc_version}")

        output_msg.append(f"Output directory: {output_dir}")
        output_msg.append("")

        if result.stdout:
            output_msg.append("Output:")
            output_msg.append(result.stdout)

        if verbose and result.stderr:
            output_msg.append("\nVerbose output:")
            output_msg.append(result.stderr)

        return "\n".join(output_msg)

    except subprocess.TimeoutExpired:
        return "Error: veritas command timed out after 5 minutes"
    except Exception as e:
        return f"Error: Failed to run veritas: {e}"

@mcp.tool()
def detect_platform() -> str:
    """
    Detect the cluster platform (Azure or Baremetal).

    Returns:
        Platform type: "azure", "baremetal", or error message
    """
    # Check for Azure-specific resources
    azure_cmd = "kubectl get nodes -o json | jq -r '.items[0].spec.providerID' 2>/dev/null"
    result = subprocess.run(azure_cmd, shell=True, capture_output=True, text=True)

    if result.returncode == 0 and result.stdout:
        provider_id = result.stdout.strip()
        if "azure://" in provider_id:
            return "azure"

    # Check for cloud provider labels
    label_cmd = "kubectl get nodes -o json | jq -r '.items[0].metadata.labels[\"node.kubernetes.io/instance-type\"]' 2>/dev/null"
    result = subprocess.run(label_cmd, shell=True, capture_output=True, text=True)

    if result.returncode == 0 and result.stdout and result.stdout.strip():
        instance_type = result.stdout.strip()
        if "Standard_" in instance_type:  # Azure instance types start with Standard_
            return "azure"

    # Check infrastructure resource (OpenShift specific)
    infra_cmd = "oc get infrastructure cluster -o json 2>/dev/null | jq -r '.status.platformStatus.type'"
    result = subprocess.run(infra_cmd, shell=True, capture_output=True, text=True)

    if result.returncode == 0 and result.stdout:
        platform = result.stdout.strip()
        if platform.lower() == "azure":
            return "azure"
        elif platform.lower() in ["baremetal", "none"]:
            return "baremetal"

    # Default to baremetal if we can't determine
    return "baremetal"

@mcp.tool()
def detect_tee() -> str:
    """
    Detect the TEE type (TDX or SNP) from cluster nodes.

    Returns:
        TEE type: "tdx", "snp", or error message
    """
    # Check for TDX
    tdx_cmd = "kubectl get nodes -o json | jq -r '.items[0].metadata.labels[\"feature.node.kubernetes.io/cpu-tdx.enabled\"]' 2>/dev/null"
    result = subprocess.run(tdx_cmd, shell=True, capture_output=True, text=True)

    if result.returncode == 0 and result.stdout.strip() == "true":
        return "tdx"

    # Check for SNP
    snp_cmd = "kubectl get nodes -o json | jq -r '.items[0].metadata.labels[\"feature.node.kubernetes.io/cpu-security.sev.snp\"]' 2>/dev/null"
    result = subprocess.run(snp_cmd, shell=True, capture_output=True, text=True)

    if result.returncode == 0 and result.stdout.strip() == "true":
        return "snp"

    # Alternative: check loaded kernel modules
    node_cmd = "kubectl get nodes -o jsonpath='{.items[0].metadata.name}'"
    result = subprocess.run(node_cmd, shell=True, capture_output=True, text=True)

    if result.returncode == 0 and result.stdout:
        node_name = result.stdout.strip()

        # Check for TDX module
        tdx_module_cmd = f"kubectl debug node/{node_name} -it --image=registry.access.redhat.com/ubi9/ubi -- chroot /host lsmod 2>/dev/null | grep -q tdx && echo 'true' || echo 'false'"
        result = subprocess.run(tdx_module_cmd, shell=True, capture_output=True, text=True, timeout=30)
        if "true" in result.stdout:
            return "tdx"

        # Check for SNP in /proc/cpuinfo
        snp_cpu_cmd = f"kubectl debug node/{node_name} -it --image=registry.access.redhat.com/ubi9/ubi -- chroot /host grep -q sev_snp /proc/cpuinfo && echo 'true' || echo 'false'"
        result = subprocess.run(snp_cpu_cmd, shell=True, capture_output=True, text=True, timeout=30)
        if "true" in result.stdout:
            return "snp"

    return "Error: Unable to detect TEE type. Check node labels or kernel modules."

@mcp.tool()
def detect_ocp_version() -> str:
    """
    Detect the OpenShift/OCP version from the cluster.

    Returns:
        OCP version string (e.g., "4.20.15") or error message
    """
    # Try OpenShift specific command first
    oc_cmd = "oc version -o json 2>/dev/null | jq -r '.openshiftVersion'"
    result = subprocess.run(oc_cmd, shell=True, capture_output=True, text=True)

    if result.returncode == 0 and result.stdout and result.stdout.strip() != "null":
        return result.stdout.strip()

    # Try clusterversion resource
    cv_cmd = "oc get clusterversion version -o jsonpath='{.status.desired.version}' 2>/dev/null"
    result = subprocess.run(cv_cmd, shell=True, capture_output=True, text=True)

    if result.returncode == 0 and result.stdout:
        return result.stdout.strip()

    # Fallback to kubectl version
    k8s_cmd = "kubectl version -o json 2>/dev/null | jq -r '.serverVersion.gitVersion'"
    result = subprocess.run(k8s_cmd, shell=True, capture_output=True, text=True)

    if result.returncode == 0 and result.stdout:
        version = result.stdout.strip()
        # Try to extract OCP version from Kubernetes version
        # OpenShift versions are typically in the format v1.x.y+hash
        return version

    return "Error: Unable to detect OCP version. Is this an OpenShift cluster?"

@mcp.tool()
def detect_cluster_config() -> str:
    """
    Detect all cluster configuration: platform, TEE, and OCP version.

    Returns:
        JSON string with platform, tee, and ocp_version fields
    """
    platform = detect_platform()
    tee = detect_tee()
    ocp_version = detect_ocp_version()

    config = {
        "platform": platform,
        "tee": tee,
        "ocp_version": ocp_version
    }

    return json.dumps(config, indent=2)

@mcp.tool()
def update_reference_values_configmap() -> str:
    """
    Update the trusteeconfig-rvps-reference-values ConfigMap with values from rvps-reference-values.

    This syncs the generated reference values (from rvps-reference-values ConfigMap) to the
    operator-managed ConfigMap (trusteeconfig-rvps-reference-values) that is mounted by the
    trustee deployment.

    The source ConfigMap has data in the 'reference-values' key (YAML string), while the
    target ConfigMap needs it in the 'reference-values.json' key (JSON string) which is
    what RVPS actually reads.

    Returns:
        Success message or error message
    """
    try:
        import yaml
        import tempfile

        # Get the reference values data from source ConfigMap
        result = subprocess.run(
            ["kubectl", "get", "configmap", "rvps-reference-values", "-n", "trustee-operator-system",
             "-o", "jsonpath={.data.reference-values}"],
            capture_output=True, text=True
        )

        if result.returncode != 0:
            return "Error: Source ConfigMap 'rvps-reference-values' not found. Run generate_reference_values() first."

        ref_values = result.stdout

        if not ref_values or ref_values.strip() == "":
            return "Error: Source ConfigMap 'rvps-reference-values' has no data in 'reference-values' key."

        # Get the current target ConfigMap
        result = subprocess.run(
            ["kubectl", "get", "configmap", "trusteeconfig-rvps-reference-values", "-n", "trustee-operator-system", "-o", "yaml"],
            capture_output=True, text=True
        )

        if result.returncode != 0:
            return "Error: Target ConfigMap 'trusteeconfig-rvps-reference-values' not found. Is the trustee operator deployed?"

        # Parse the ConfigMap
        cm = yaml.safe_load(result.stdout)

        # Update the reference-values.json key (this is what RVPS reads)
        if 'data' not in cm:
            cm['data'] = {}

        cm['data']['reference-values.json'] = ref_values

        # Also update the reference-values key for consistency
        cm['data']['reference-values'] = ref_values

        # Write to temporary file and apply
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(cm, f)
            temp_file = f.name

        try:
            result = subprocess.run(
                ["kubectl", "apply", "-f", temp_file],
                capture_output=True, text=True
            )

            if result.returncode != 0:
                return f"Error: Failed to apply ConfigMap\n{result.stderr}"

            return (
                "Successfully updated trusteeconfig-rvps-reference-values ConfigMap.\n"
                "Updated both 'reference-values' and 'reference-values.json' keys.\n\n"
                "The new reference values will be automatically synced to the trustee pod within 60-90 seconds.\n"
                "To force immediate pickup, restart the trustee deployment:\n"
                "  kubectl rollout restart deployment/trustee-deployment -n trustee-operator-system"
            )
        finally:
            # Clean up temp file
            import os
            try:
                os.unlink(temp_file)
            except:
                pass

    except ImportError:
        return "Error: PyYAML library is required. Install it with: pip install pyyaml"
    except Exception as e:
        return f"Error: Failed to update ConfigMap: {e}"

@mcp.tool()
def generate_baremetal_tdx_values(
    ocp_version: str = None,
    authfile: str = None,
    initdata: str = "initdata.toml",
    output_dir: str = ".",
    verbose: bool = False
) -> str:
    """
    Generate reference values for Baremetal TDX.
    Auto-detects OCP version if not provided.

    Args:
        ocp_version: OCP version (e.g., "4.20.15", auto-detected if not provided)
        authfile: Path to registry auth file (pull-secret.json)
        initdata: Path to initdata.toml file (default: "initdata.toml")
        output_dir: Output directory (default: current directory)
        verbose: Enable verbose output

    Returns:
        Success message with output location or error message
    """
    return generate_reference_values(
        platform="baremetal",
        tee="tdx",
        ocp_version=ocp_version,
        authfile=authfile,
        initdata=initdata,
        output_dir=output_dir,
        verbose=verbose
    )

@mcp.tool()
def generate_baremetal_snp_values(
    ocp_version: str = None,
    authfile: str = None,
    initdata: str = "initdata.toml",
    output_dir: str = ".",
    verbose: bool = False
) -> str:
    """
    Generate reference values for Baremetal SNP.
    Auto-detects OCP version if not provided.

    Args:
        ocp_version: OCP version (e.g., "4.20.15", auto-detected if not provided)
        authfile: Path to registry auth file (pull-secret.json)
        initdata: Path to initdata.toml file (default: "initdata.toml")
        output_dir: Output directory (default: current directory)
        verbose: Enable verbose output

    Returns:
        Success message with output location or error message
    """
    return generate_reference_values(
        platform="baremetal",
        tee="snp",
        ocp_version=ocp_version,
        authfile=authfile,
        initdata=initdata,
        output_dir=output_dir,
        verbose=verbose
    )

@mcp.tool()
def generate_azure_tdx_values(
    osc_version: str = None,
    authfile: str = None,
    initdata: str = "initdata.toml",
    output_dir: str = ".",
    verbose: bool = False
) -> str:
    """
    Generate reference values for Azure TDX.

    Args:
        osc_version: OSC dm-verity image tag (optional, defaults to latest)
        authfile: Path to registry auth file (pull-secret.json)
        initdata: Path to initdata.toml file (default: "initdata.toml")
        output_dir: Output directory (default: current directory)
        verbose: Enable verbose output

    Returns:
        Success message with output location or error message
    """
    return generate_reference_values(
        platform="azure",
        tee="tdx",
        osc_version=osc_version,
        authfile=authfile,
        initdata=initdata,
        output_dir=output_dir,
        verbose=verbose
    )

@mcp.tool()
def generate_azure_snp_values(
    osc_version: str = None,
    authfile: str = None,
    initdata: str = "initdata.toml",
    output_dir: str = ".",
    verbose: bool = False
) -> str:
    """
    Generate reference values for Azure SNP.

    Args:
        osc_version: OSC dm-verity image tag (optional, defaults to latest)
        authfile: Path to registry auth file (pull-secret.json)
        initdata: Path to initdata.toml file (default: "initdata.toml")
        output_dir: Output directory (default: current directory)
        verbose: Enable verbose output

    Returns:
        Success message with output location or error message
    """
    return generate_reference_values(
        platform="azure",
        tee="snp",
        osc_version=osc_version,
        authfile=authfile,
        initdata=initdata,
        output_dir=output_dir,
        verbose=verbose
    )

@mcp.tool()
def generate_attestation_token_keypair(
    key_file: str = "token.key",
    cert_file: str = "token.crt",
    days_valid: int = 365,
    subject: str = "/CN=kbs-trustee-operator-system/O=RedHat"
) -> str:
    """
    Generate EC key and self-signed certificate for attestation tokens.

    Args:
        key_file: Output file for the private key (default: "token.key")
        cert_file: Output file for the certificate (default: "token.crt")
        days_valid: Number of days the certificate is valid (default: 365)
        subject: Certificate subject DN (default: "/CN=kbs-trustee-operator-system/O=RedHat")

    Returns:
        Success message with file locations or error message
    """
    try:
        # Step 1: Generate EC private key (prime256v1 curve)
        key_cmd = [
            "openssl", "ecparam",
            "-name", "prime256v1",
            "-genkey",
            "-noout",
            "-out", key_file
        ]

        result = subprocess.run(key_cmd, capture_output=True, text=True)

        if result.returncode != 0:
            return f"Error: Failed to generate private key\n{result.stderr}"

        # Step 2: Generate self-signed certificate
        cert_cmd = [
            "openssl", "req",
            "-new",
            "-x509",
            "-key", key_file,
            "-out", cert_file,
            "-days", str(days_valid),
            "-subj", subject
        ]

        result = subprocess.run(cert_cmd, capture_output=True, text=True)

        if result.returncode != 0:
            return f"Error: Failed to generate certificate\n{result.stderr}"

        # Verify both files exist
        if not os.path.exists(key_file):
            return f"Error: Private key file {key_file} was not created"

        if not os.path.exists(cert_file):
            return f"Error: Certificate file {cert_file} was not created"

        # Get file sizes for confirmation
        key_size = os.path.getsize(key_file)
        cert_size = os.path.getsize(cert_file)

        return (
            f"Successfully generated attestation token keypair:\n"
            f"  Private key: {key_file} ({key_size} bytes)\n"
            f"  Certificate: {cert_file} ({cert_size} bytes)\n"
            f"  Subject: {subject}\n"
            f"  Valid for: {days_valid} days"
        )

    except Exception as e:
        return f"Error: Failed to generate keypair: {e}"

@mcp.tool()
def generate_https_keypair(
    key_file: str = "tls.key",
    cert_file: str = "tls.crt",
    days_valid: int = 365,
    subject: str = "/CN=kbs-trustee-operator-system/O=Red Hat",
    route_name: str = None,
    namespace: str = "trustee-operator-system"
) -> str:
    """
    Generate RSA key and self-signed certificate for HTTPS with OpenShift route as SAN.

    Args:
        key_file: Output file for the private key (default: "tls.key")
        cert_file: Output file for the certificate (default: "tls.crt")
        days_valid: Number of days the certificate is valid (default: 365)
        subject: Certificate subject DN (default: "/CN=kbs-trustee-operator-system/O=Red Hat")
        route_name: Route name (default: "kbs-route", will be combined with namespace and domain)
        namespace: Namespace for the route (default: "trustee-operator-system")

    Returns:
        Success message with file locations or error message
    """
    try:
        # Step 1: Get the cluster domain
        domain_cmd = "oc get ingress.config/cluster -o jsonpath='{.spec.domain}'"
        result = subprocess.run(domain_cmd, shell=True, capture_output=True, text=True)

        if result.returncode != 0:
            return f"Error: Failed to get cluster domain\n{result.stderr}"

        domain = result.stdout.strip()
        if not domain:
            return "Error: Cluster domain is empty. Is this an OpenShift cluster?"

        # Step 2: Build the full route FQDN
        if route_name is None:
            route_name = "kbs-route"

        route_fqdn = f"{route_name}-{namespace}.{domain}"

        # Step 3: Generate RSA key and self-signed certificate with SAN
        cert_cmd = [
            "openssl", "req",
            "-x509",
            "-nodes",
            "-days", str(days_valid),
            "-newkey", "rsa:2048",
            "-keyout", key_file,
            "-out", cert_file,
            "-subj", subject,
            "-addext", f"subjectAltName=DNS:{route_fqdn}"
        ]

        result = subprocess.run(cert_cmd, capture_output=True, text=True)

        if result.returncode != 0:
            return f"Error: Failed to generate certificate\n{result.stderr}"

        # Verify both files exist
        if not os.path.exists(key_file):
            return f"Error: Private key file {key_file} was not created"

        if not os.path.exists(cert_file):
            return f"Error: Certificate file {cert_file} was not created"

        # Get file sizes for confirmation
        key_size = os.path.getsize(key_file)
        cert_size = os.path.getsize(cert_file)

        return (
            f"Successfully generated HTTPS keypair:\n"
            f"  Private key: {key_file} ({key_size} bytes)\n"
            f"  Certificate: {cert_file} ({cert_size} bytes)\n"
            f"  Subject: {subject}\n"
            f"  SAN: DNS:{route_fqdn}\n"
            f"  Valid for: {days_valid} days\n\n"
            f"Cluster domain: {domain}"
        )

    except Exception as e:
        return f"Error: Failed to generate HTTPS keypair: {e}"

@mcp.tool()
def create_trustee_config(
    profile: str = "permissive",
    namespace: str = "trustee-operator-system",
    config_name: str = "trusteeconfig",
    kbs_service_type: str = "ClusterIP"
) -> str:
    """
    Create a TrusteeConfig resource with permissive or restrictive security profile.

    Args:
        profile: Security profile - "permissive" or "restrictive" (default: "permissive")
        namespace: Namespace to create resources in (default: "trustee-operator-system")
        config_name: Name of the TrusteeConfig resource (default: "trusteeconfig")
        kbs_service_type: Kubernetes service type - "ClusterIP" or "LoadBalancer" (default: "ClusterIP")

    Returns:
        Success message or error message

    Notes:
        - Permissive profile: Creates basic TrusteeConfig without custom certificates
        - Restrictive profile: Generates HTTPS and attestation token keypairs, creates secrets,
          and configures TrusteeConfig to use them
    """
    import tempfile
    import yaml

    try:
        if profile not in ["permissive", "restrictive"]:
            return "Error: profile must be 'permissive' or 'restrictive'"

        output_messages = []

        # Restrictive profile: generate keypairs and create secrets
        https_secret_name = None
        token_secret_name = None

        if profile == "restrictive":
            output_messages.append("=== Restrictive Profile: Generating Keypairs ===\n")

            # Generate HTTPS keypair
            https_result = generate_https_keypair(
                key_file="tls.key",
                cert_file="tls.crt",
                namespace=namespace
            )
            if https_result.startswith("Error:"):
                return https_result
            output_messages.append(https_result)
            output_messages.append("")

            # Generate attestation token keypair
            token_result = generate_attestation_token_keypair(
                key_file="token.key",
                cert_file="token.crt"
            )
            if token_result.startswith("Error:"):
                return token_result
            output_messages.append(token_result)
            output_messages.append("")

            # Create secrets
            output_messages.append("=== Creating Kubernetes Secrets ===\n")

            # Verify the generated key and cert files exist
            if not os.path.exists("tls.key") or not os.path.exists("tls.crt"):
                return "Error: HTTPS key/cert files not found"

            # Create HTTPS TLS secret (combined key and cert in kubernetes.io/tls format)
            https_secret_name = f"{config_name}-https-secret"
            https_secret_cmd = [
                "kubectl", "create", "secret", "tls",
                https_secret_name,
                "--cert=tls.crt",
                "--key=tls.key",
                "-n", namespace,
                "--dry-run=client",
                "-o", "yaml"
            ]

            result = subprocess.run(https_secret_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                return f"Error: Failed to create HTTPS secret YAML\n{result.stderr}"

            apply_result = subprocess.run(
                ["kubectl", "apply", "-f", "-"],
                input=result.stdout,
                capture_output=True,
                text=True
            )
            if apply_result.returncode != 0:
                return f"Error: Failed to apply HTTPS secret\n{apply_result.stderr}"

            output_messages.append(f"Created secret: {https_secret_name}")

            # Create attestation token secret (using token.key/token.crt files)
            token_secret_name = f"{config_name}-token-secret"
            token_secret_cmd = [
                "kubectl", "create", "secret", "tls",
                token_secret_name,
                "--cert=token.crt",
                "--key=token.key",
                "-n", namespace,
                "--dry-run=client",
                "-o", "yaml"
            ]

            result = subprocess.run(token_secret_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                return f"Error: Failed to create token secret YAML\n{result.stderr}"

            # Apply token secret
            apply_result = subprocess.run(
                ["kubectl", "apply", "-f", "-"],
                input=result.stdout,
                capture_output=True,
                text=True
            )
            if apply_result.returncode != 0:
                return f"Error: Failed to apply token secret\n{apply_result.stderr}"

            output_messages.append(f"Created secret: {token_secret_name}")
            output_messages.append("")

        # Create ConfigMaps
        output_messages.append("=== Creating ConfigMaps ===\n")

        # Read kbs-config template
        # Map "restrictive" to "restricted" for KBS config template filename
        kbs_template_profile = "restricted" if profile == "restrictive" else profile
        kbs_config_template = f"kbs-config-{kbs_template_profile}.toml"
        kbs_config_path = os.path.join(TRUSTEE_REPO_PATH, "config/templates", kbs_config_template)
        try:
            with open(kbs_config_path, "r") as f:
                kbs_config_content = f.read()
        except FileNotFoundError:
            return f"Error: KBS config template not found: {kbs_config_path}"

        # Read resource-policy template (uses "restrictive" not "restricted")
        resource_policy_template = f"resource-policy-{profile}.rego"
        resource_policy_path = os.path.join(TRUSTEE_REPO_PATH, "config/templates", resource_policy_template)
        try:
            with open(resource_policy_path, "r") as f:
                resource_policy_content = f.read()
        except FileNotFoundError:
            return f"Error: Resource policy template not found: {resource_policy_path}"

        # Create kbs-config ConfigMap
        kbs_config_cm = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {
                "name": f"{config_name}-kbs-config",
                "namespace": namespace
            },
            "data": {
                "kbs-config.toml": kbs_config_content
            }
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(kbs_config_cm, f)
            kbs_config_file = f.name

        try:
            result = subprocess.run(
                ["kubectl", "apply", "-f", kbs_config_file],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                return f"Error: Failed to create kbs-config ConfigMap\n{result.stderr}"
            output_messages.append(f"Created ConfigMap: {config_name}-kbs-config")
        finally:
            try:
                os.unlink(kbs_config_file)
            except:
                pass

        # Create resource-policy ConfigMap
        resource_policy_cm = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {
                "name": f"{config_name}-resource-policy",
                "namespace": namespace
            },
            "data": {
                "policy.rego": resource_policy_content
            }
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(resource_policy_cm, f)
            resource_policy_file = f.name

        try:
            result = subprocess.run(
                ["kubectl", "apply", "-f", resource_policy_file],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                return f"Error: Failed to create resource-policy ConfigMap\n{result.stderr}"
            output_messages.append(f"Created ConfigMap: {config_name}-resource-policy")
        finally:
            try:
                os.unlink(resource_policy_file)
            except:
                pass

        output_messages.append("")

        # Create TrusteeConfig
        output_messages.append("=== Creating TrusteeConfig ===\n")

        trustee_config = {
            "apiVersion": "confidentialcontainers.org/v1alpha1",
            "kind": "TrusteeConfig",
            "metadata": {
                "name": config_name,
                "namespace": namespace
            },
            "spec": {
                "profileType": profile.capitalize(),
                "kbsServiceType": kbs_service_type
            }
        }

        # Add restrictive profile settings
        if profile == "restrictive":
            trustee_config["spec"]["httpsSpec"] = {
                "tlsSecretName": https_secret_name
            }
            trustee_config["spec"]["attestationTokenVerificationSpec"] = {
                "tlsSecretName": token_secret_name
            }

        # Write to temporary file and apply
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(trustee_config, f)
            temp_file = f.name

        try:
            result = subprocess.run(
                ["kubectl", "apply", "-f", temp_file],
                capture_output=True,
                text=True
            )

            if result.returncode != 0:
                return f"Error: Failed to apply TrusteeConfig\n{result.stderr}"

            output_messages.append(f"Created TrusteeConfig: {config_name}")
            output_messages.append(f"Profile Type: {profile}")
            output_messages.append(f"Service Type: {kbs_service_type}")

            output_messages.append(f"\nConfigMaps:")
            output_messages.append(f"  KBS Config: {config_name}-kbs-config")
            output_messages.append(f"  Resource Policy: {config_name}-resource-policy")

            if profile == "restrictive":
                output_messages.append(f"\nSecurity settings:")
                output_messages.append(f"  HTTPS TLS Secret: {https_secret_name}")
                output_messages.append(f"  Attestation Token Verification Secret: {token_secret_name}")

            output_messages.append("\n✓ TrusteeConfig created successfully!")

            return "\n".join(output_messages)

        finally:
            # Clean up temp file
            try:
                os.unlink(temp_file)
            except:
                pass

    except ImportError:
        return "Error: PyYAML library is required. Install it with: pip install pyyaml"
    except Exception as e:
        return f"Error: Failed to create TrusteeConfig: {e}"

@mcp.tool()
def delete_trustee_config(
    config_name: str = "trusteeconfig",
    namespace: str = "trustee-operator-system",
    delete_secrets: bool = True
) -> str:
    """
    Delete the TrusteeConfig CR and optionally associated secrets.

    Args:
        config_name: Name of the TrusteeConfig resource to delete (default: "trusteeconfig")
        namespace: Namespace where the TrusteeConfig exists (default: "trustee-operator-system")
        delete_secrets: Also delete associated secrets (HTTPS and token secrets) (default: True)

    Returns:
        Success message with details of what was deleted, or error message
    """
    try:
        import yaml

        output_messages = []
        output_messages.append("=== Deleting TrusteeConfig ===\n")

        # First, get the TrusteeConfig to check if it exists and get secret names
        get_cmd = [
            "kubectl", "get", "trusteeconfig", config_name,
            "-n", namespace,
            "-o", "yaml"
        ]

        result = subprocess.run(get_cmd, capture_output=True, text=True)

        secret_names = []
        if result.returncode == 0:
            try:
                config = yaml.safe_load(result.stdout)
                spec = config.get("spec", {})

                # Extract secret names from the config
                https_spec = spec.get("httpsSpec", {})
                https_secret = https_spec.get("tlsSecretName")

                attestation_spec = spec.get("attestationTokenVerificationSpec", {})
                token_secret = attestation_spec.get("tlsSecretName")

                # Collect unique secret names
                if https_secret:
                    secret_names.append(https_secret)
                if token_secret and token_secret not in secret_names:
                    secret_names.append(token_secret)

            except Exception as e:
                output_messages.append(f"Warning: Could not parse TrusteeConfig to find secrets: {e}\n")
        else:
            # TrusteeConfig doesn't exist
            return f"TrusteeConfig '{config_name}' not found in namespace '{namespace}'"

        # Delete the TrusteeConfig
        delete_cmd = [
            "kubectl", "delete", "trusteeconfig", config_name,
            "-n", namespace
        ]

        result = subprocess.run(delete_cmd, capture_output=True, text=True)

        if result.returncode != 0:
            return f"Error: Failed to delete TrusteeConfig\n{result.stderr}"

        output_messages.append(f"✓ Deleted TrusteeConfig: {config_name}")

        # Delete ConfigMaps
        output_messages.append("\n=== Deleting Associated ConfigMaps ===\n")

        configmap_names = [
            f"{config_name}-kbs-config",
            f"{config_name}-resource-policy"
        ]

        for cm_name in configmap_names:
            delete_cm_cmd = [
                "kubectl", "delete", "configmap", cm_name,
                "-n", namespace,
                "--ignore-not-found=true"
            ]

            result = subprocess.run(delete_cm_cmd, capture_output=True, text=True)

            if result.returncode == 0:
                output_messages.append(f"✓ Deleted ConfigMap: {cm_name}")
            else:
                output_messages.append(f"⚠ Failed to delete ConfigMap: {cm_name}\n  {result.stderr.strip()}")

        # Delete secrets if requested and found
        if delete_secrets and secret_names:
            output_messages.append("\n=== Deleting Associated Secrets ===\n")

            for secret_name in secret_names:
                delete_secret_cmd = [
                    "kubectl", "delete", "secret", secret_name,
                    "-n", namespace,
                    "--ignore-not-found=true"
                ]

                result = subprocess.run(delete_secret_cmd, capture_output=True, text=True)

                if result.returncode == 0:
                    output_messages.append(f"✓ Deleted secret: {secret_name}")
                else:
                    output_messages.append(f"⚠ Failed to delete secret: {secret_name}\n  {result.stderr.strip()}")

        elif delete_secrets and not secret_names:
            output_messages.append("\nNo custom secrets were configured in the TrusteeConfig")

        output_messages.append("\n✓ TrusteeConfig deletion completed successfully!")

        return "\n".join(output_messages)

    except ImportError:
        return "Error: PyYAML library is required. Install it with: pip install pyyaml"
    except Exception as e:
        return f"Error: Failed to delete TrusteeConfig: {e}"

if __name__ == "__main__":
    mcp.run()
