# AArch64 target baseline. A recipe can override the branch protection level.
*self_spec:
+ %{!mbranch-protection=*:-mbranch-protection=standard}
