import request from './request'

export interface Record {
    id: number
    book_id: number
    type: string
    amount: number
    account_id: number | null
    target_account_id: number | null
    category_id: number | null
    record_time: string
    payee: string | null
    remark: string | null
    creator_id: number
}

// Get records by book_id
export const getRecords = (bookId: number) => {
    return request.get<Record[]>('/accounting/records', { params: { book_id: bookId } })
}

// Upload CSV file for import
export const importCsv = (bookId: number, file: File) => {
    const formData = new FormData()
    formData.append('file', file)

    return request.post<{ message: string }>(`/accounting/import/csv?book_id=${bookId}`, formData, {
        headers: {
            'Content-Type': 'multipart/form-data'
        }
    })
}
