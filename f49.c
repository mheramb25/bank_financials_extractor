#include<stdio.h>

int fact(int n);

int main()
{
    int n;
    printf("enter a numb:\n");
    scanf("%d",&n);
    int ans=fact(n);
    printf("the factorial of %d is:%d",n,ans);
    return 0;
}

int fact(int n)
{
    if(n==0)
         return 1;
    else
        return n*fact(n-1);

}
