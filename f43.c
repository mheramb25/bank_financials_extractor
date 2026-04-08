#include<stdio.h>

//function declaration
//return_data_type name(parameters)
int sum(int a,int b)
{
    int ans=a+b;
    return ans;
}

int main()
{
    int a;
    printf("enter number1:\n");
    scanf("%d",&a);
    int b;
    printf("enter number2:\n");
    scanf("%d",&b);
    int ans=sum(a,b);
    printf("the sum is:%d",ans);
    return 0;
}

