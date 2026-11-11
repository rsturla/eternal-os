%{
#include <stdio.h>
#include <stdlib.h>
int yylex(void);
void yyerror(const char *s);
%}
%token NUMBER
%left '+'
%%
input: expr '\n' { printf("%d\n", $1); };
expr: NUMBER | expr '+' expr { $$ = $1 + $3; };
%%
/* The fixture grammar accepts single-digit operands and '+' expressions. */
int yylex(void) {
  int character;
  do {
    character = getchar();
  } while (character == ' ');
  if (character >= '0' && character <= '9') {
    yylval = character - '0';
    return NUMBER;
  }
  return character == EOF ? 0 : character;
}

void yyerror(const char *message) {
  fprintf(stderr, "%s\n", message);
}

int main(void) {
  return yyparse();
}
