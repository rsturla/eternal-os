extern int yywrap(void);
int yylex(void) { return 0; }
int main(void) { return yywrap() != 1; }
