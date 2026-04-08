#include<stdio.h>

int main()
{
    int len;
    printf("enter the length of array:\n");
    scanf("%d",&len);

    int arr1[len];
    for(int i=0;i<len;i++)
    {
        printf("enter nos.\n");
        scanf("%d",&arr1[i]);
    }
    int count=0;
    for(int i=0;i<len;i++)
    {
        count+=arr1[i];
    }
    printf("the sum is:%d\n",count);    
    
    return 0;
}