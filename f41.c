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
    int index=-1;
    int num;
    printf("enter the number whose index you want to find:\n");
    scanf("%d",&num);   

    for(int i=0;i<len;i++)
    {
        if(arr1[i]==num)
        {
            printf("the index of %d is:%d\n",arr1[i],i);
            index=i;
            break;
            
        }
    }
if(index==-1)
    {
        printf("the number is not found in the array\n");
    } 
     
    return 0;
}