import type { ApiError } from 'agent';
export class ApiClientError extends Error {
 constructor(public status:number,public error:ApiError){super(error.message);this.name='ApiClientError';}
}
export async function request<T>(path:string,init:RequestInit={}):Promise<T>{
 const response=await fetch(path,{...init,headers:{Accept:'application/json',...init.headers}});
 if(!response.ok){let error:ApiError;try{error=await response.json();}catch{error={code:'HTTP_ERROR',message:`HTTP ${response.status}`,requestId:''};}throw new ApiClientError(response.status,error);}
 return response.json() as Promise<T>;
}
