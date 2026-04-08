#include<stdio.h>

int main()
{
    int a=10;
    printf("the value of a is:%d\n",a);
    printf("the address of a is:%p\n",&a); //%p is used to print memory address

    int *p;
    p=&a; //linking pointer p to address of variable a

    printf("linked pointer p to variable a\n");
    //a and *p are now pointing to the same value and changing one will change the other
    printf("the value of a is:%d\n",a);
    printf("the value of *p is:%d\n",*p); 

    printf("the address of a is:%p\n",&a);
    printf("the value stored in p is:%p\n",p); 

    int b=30;
    p=&b;
    printf("*p will print value of b:%d\n",*p);
    *p=300;
    printf("b after changing value of *p is:%d\n",b);
    return 0;


}

