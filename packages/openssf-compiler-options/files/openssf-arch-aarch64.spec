# AArch64 target baseline. BFD translates AEABI branch-protection attributes
# into the GNU properties used by the loader; Gold does not. Recipes can
# explicitly select a different linker or branch protection level.
*self_spec:
+ %{!mbranch-protection=*:-mbranch-protection=standard} \
  %{!fuse-ld=*:-fuse-ld=bfd}
