# x86-64 target baseline. A recipe can override either flag explicitly.
*self_spec:
+ %{!march=*:-march=x86-64-v2} \
  %{!fcf-protection=*:-fcf-protection=full}
