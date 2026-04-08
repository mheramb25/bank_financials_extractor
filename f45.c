#include<stdio.h>

//global var
int abc=10;

void swap(int a,int b)
{
    int temp=a;
    a=b;
    b=temp;
    printf("in function swap - a-%d:b-%d\n",a,b);
}

void swapwithpointer(int *p1,int *p2)
{
    int temp=*p1;
    *p1=*p2;
    *p2=temp;
    printf("in function swapwithpointer - *p1-%d:*p2-%d\n",*p1,*p2);
}

int main()
{
    int a=10,b=20;
    swap(a,b);
    printf("after calling function swap,in main - a-%d:b-%d\n",a,b);
    swapwithpointer(&a,&b);
    printf("after calling function swapwithpointer a-%d:b-%d\n",a,b);

    return 0;
}
