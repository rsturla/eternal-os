repo available 0 testtags <inline>
#>=Pkg: broken 1 1 noarch
#>=Req: absent-dependency
system x86_64 rpm
job install name broken
result transaction,problems <inline>
#>problem e049b46a info nothing provides absent-dependency needed by broken-1-1.noarch
#>problem e049b46a solution d280a3d1 deljob install name broken
