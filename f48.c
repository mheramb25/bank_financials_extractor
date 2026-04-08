#include<stdio.h>
#include<string.h>

int main()
{
    char str[80],*p;
    printf("enter a line of string:\n");
    if(fgets(str,80,stdin)==NULL)
       printf("error\n");

    if(p=strchr(str,'\n')) *p='\0'; 

    puts(str);
    return 0;
     
}