AC_INIT([eternal-fixture], [1.0])
AC_CONFIG_SRCDIR([configure.ac])
AC_PROG_CC
AC_CHECK_HEADERS([stdio.h], [], [AC_MSG_ERROR([stdio.h missing])])
AC_ARG_ENABLE([feature], [], [], [enable_feature=no])
AS_CASE([$enable_feature], [yes], [AC_DEFINE([FEATURE_ENABLED], [1], [Whether the feature is enabled])], [no], [], [AC_MSG_ERROR([invalid feature value])])
AC_CONFIG_HEADERS([config.h])
AC_OUTPUT
