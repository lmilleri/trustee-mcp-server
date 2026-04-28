# MCP Tool Improvements

Based on the troubleshooting session on 2026-04-28, here are the critical improvements needed:

## 1. Add `generate_reference_values_from_node()` Function

**Problem**: `veritas` extracts binaries from OCP release, but nodes may have newer versions (e.g., node had `edk2-ovmf-20241117-4.el9_7.3` but OCP 4.21.11 had `edk2-ovmf-20241117-2.el9_6.2`). This causes SNP measurement mismatches.

**Solution**: Add a function that:
- Deploys a compute pod on the target node
- Mounts the actual kata/ovmf directories from the node
- Installs `sev-snp-measure` in the pod
- Computes SNP measurement using the actual node binaries
- Extracts all required attestation values from the running pod

**Benefits**:
- Always generates correct measurements that match what's actually running
- Eliminates version mismatch issues
- Doesn't depend on veritas or OCP release versions

**Implementation sketch**:
```python
@mcp.tool()
def generate_reference_values_from_node(
    node_name: str = None,
    authfile: str = "pull-secret.json",
    initdata: str = "initdata.toml",
    output_dir: str = "."
) -> str:
    """
    Generate reference values by computing measurements directly on a cluster node.
    
    This is more reliable than using OCP release artifacts because it uses
    the actual binaries deployed on the node.
    
    Args:
        node_name: Node to use (auto-detects a suitable node if not provided)
        authfile: Path to pull secret
        initdata: Path to initdata.toml
        output_dir: Output directory
    
    Returns:
        Success message with generated values
    """
    # 1. Auto-detect node if not provided (find one with kata)
    # 2. Create compute pod on that node with host mounts
    # 3. Install sev-snp-measure in pod
    # 4. Get actual QEMU parameters from ps output
    # 5. Compute SNP measurement with actual binaries
    # 6. Extract all platform values (SMT, TSME, policy, TCB)
    # 7. Generate complete ConfigMap with ALL required values
    # 8. Clean up pod
```

## 2. Include ALL OPA-Required Reference Values

**Problem**: Current implementation only generates `snp_launch_measurement` and `init_data`, but OPA policy requires:
- Configuration: `snp_smt_enabled`, `snp_tsme_enabled`, `snp_guest_abi_major`, `snp_guest_abi_minor`, `snp_single_socket`, `snp_smt_allowed`
- Hardware: `snp_bootloader`, `snp_microcode`, `snp_snp_svn`, `snp_tee_svn`

**Solution**: Modify `generate_reference_values()` and the new `generate_reference_values_from_node()` to:
1. Query the attestation service for what the pod reports
2. Extract ALL values from the attestation claims
3. Include them in the reference values ConfigMap

**Implementation**: Add to both generation functions:
```python
# After computing SNP measurement, extract platform values
platform_values = {
    "snp_smt_enabled": claims["platform_smt_enabled"],
    "snp_tsme_enabled": claims["platform_tsme_enabled"],
    "snp_guest_abi_major": claims["policy_abi_major"],
    "snp_guest_abi_minor": claims["policy_abi_minor"],
    "snp_single_socket": claims["policy_single_socket"],
    "snp_smt_allowed": claims["policy_smt_allowed"],
    "snp_bootloader": claims["reported_tcb_bootloader"],
    "snp_microcode": claims["reported_tcb_microcode"],
    "snp_snp_svn": claims["reported_tcb_snp"],
    "snp_tee_svn": claims["reported_tcb_tee"]
}
```

## 3. Better Kernel Cmdline Detection

**Problem**: The kernel cmdline needs to include BOTH kata defaults AND pod annotations, but detection is complex.

**Current workaround**: Reads from test-pod.yaml.in template.

**Better solution**: 
```python
def detect_full_kernel_cmdline(node_name: str) -> str:
    """
    Detect the full kernel cmdline by examining actual QEMU processes.
    
    This is more reliable than trying to reconstruct it from kata config
    + annotations.
    """
    # 1. Find a running kata VM on the node
    # 2. Extract -append parameter from ps aux | grep qemu-kvm
    # 3. Return the actual cmdline being used
```

## 4. Auto-Restart Trustee After ConfigMap Update

**Problem**: After updating the ConfigMap, RVPS doesn't pick up new values until trustee pod restarts (can take 60-90 seconds).

**Solution**: Add automatic restart:
```python
def update_reference_values_configmap(...):
    # ... existing code ...
    
    # Restart trustee deployment to pick up new values immediately
    subprocess.run(
        "kubectl rollout restart deployment/trustee-deployment -n trustee-operator-system",
        shell=True
    )
    subprocess.run(
        "kubectl rollout status deployment/trustee-deployment -n trustee-operator-system --timeout=60s",
        shell=True
    )
    
    return "ConfigMap updated and trustee restarted"
```

## 5. Add Validation Function

**Problem**: No easy way to verify if reference values match what a pod is reporting.

**Solution**:
```python
@mcp.tool()
def validate_reference_values(pod_name: str = "ocp-cc-pod") -> str:
    """
    Validate that reference values in RVPS match what a pod is reporting.
    
    Compares:
    - SNP measurement
    - init_data hash
    - All platform/TCB values
    
    Returns detailed comparison report.
    """
```

## 6. Add Troubleshooting Function

**Problem**: When attestation fails, it's hard to know why.

**Solution**:
```python
@mcp.tool()
def diagnose_attestation_failure(pod_name: str = "ocp-cc-pod") -> str:
    """
    Diagnose why attestation is failing.
    
    Checks:
    1. Are reference values present in RVPS?
    2. Do measurements match?
    3. Which OPA policy rules are failing?
    4. Binary version mismatches (compare node vs OCP release)
    5. Trust vector scores and what they mean
    
    Returns detailed diagnosis with recommended fixes.
    """
```

## 7. Documentation Improvements

Add to README.md:

### Common Issues

#### SNP Measurement Mismatch
**Symptom**: `executables: 33` (Affirming - minor issues), measurement doesn't match

**Cause**: Node binaries (kernel/initrd/OVMF) don't match OCP release artifacts. Nodes may have been updated independently.

**Solution**: Use `generate_reference_values_from_node()` instead of `generate_reference_values()` to compute measurements using actual node binaries.

#### Reference Values Not Found
**Symptom**: Logs show "No reference value found for snp_bootloader"

**Cause**: Incomplete reference values in ConfigMap

**Solution**: Ensure ConfigMap includes ALL required values (see list in improvement #2)

## Priority

1. **HIGH**: Add `generate_reference_values_from_node()` - This solves the binary version mismatch
2. **HIGH**: Include all OPA-required values - Prevents "missing reference value" errors
3. **MEDIUM**: Auto-restart trustee - Improves UX
4. **MEDIUM**: Add validation function - Makes troubleshooting easier
5. **LOW**: Better cmdline detection - Current workaround is functional
6. **LOW**: Add diagnosis function - Nice to have

## Testing Plan

After implementing, test with:
1. Clean cluster with mismatched OVMF versions
2. Verify all reference values are generated
3. Verify attestation succeeds (status: affirming or warning, not contraindicated)
4. Verify measurements match

## Notes

- The `generate_milan_snp.py` workaround is NOT needed and has been deleted
- The real issue was OVMF version mismatch, not CPU signature
- SHA256/SHA384 init_data fix in server.py should be kept - that's a permanent fix
