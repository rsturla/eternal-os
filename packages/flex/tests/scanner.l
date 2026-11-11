%option noyywrap noinput nounput
%{
#include <stdio.h>
%}
%%
[a-z]+ { printf("word:%s\n",yytext); }
[0-9]+ { printf("number:%s\n",yytext); }
[ \t\n]+ ;
. { return 1; }
%%
int main(void){return yylex();}
